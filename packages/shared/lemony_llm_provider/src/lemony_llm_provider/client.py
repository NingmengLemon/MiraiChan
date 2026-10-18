"""端点池: 多 key 轮询、冷却熔断、失败换端点、流式归一化"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import anthropic
import google.genai as genai
import httpx2
import openai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from . import protocols
from .errors import (
    AuthError,
    LLMConfigError,
    LLMError,
    RequestRejected,
    StreamAborted,
    map_sdk_error,
)
from .models import (
    Completed,
    CompletionRequest,
    FinishReason,
    ReasoningDelta,
    SignatureDelta,
    StreamAccumulator,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
)
from .settings import EndpointSpec, LLMSettings, build_specs

logger = logging.getLogger(__name__)

# 冷却上限, 单位秒
COOLDOWN_CAP = 120.0
# 截断/流内报错的退避上限: 比一般错误短, 这类问题往往不是端点整体坏了
ABORT_COOLDOWN_CAP = 30.0
# 鉴权错误的冷却时间: 基本等于"本进程内不再使用"
AUTH_COOLDOWN = 3600.0
# 端点要求客户端自报身份, 不要用 SDK 或 HTTP 库的默认 UA
DEFAULT_USER_AGENT = "miraichan-llm/0.1"

# 两个 SDK 会无条件读取这些环境变量并注入每个请求, 多端点场景下会把凭据或组织信息
# 发给配置之外的第三方端点, 所以启动时直接拒绝
_SDK_ENV_HEADERS = ("OPENAI_CUSTOM_HEADERS", "ANTHROPIC_CUSTOM_HEADERS")
_SDK_ENV_IDENTITY = ("OPENAI_ORG_ID", "OPENAI_PROJECT_ID")

# 三个 SDK 各自的异常基类, 统一交给 map_sdk_error 归类
_SDK_ERRORS: tuple[type[Exception], ...] = (
    openai.OpenAIError,
    anthropic.AnthropicError,
    genai_errors.APIError,
)


async def _close_stream(stream: Any) -> None:
    """关掉一条已经打开的流: 有的 SDK 给 close, 有的只给 aclose"""
    for name in ("aclose", "close"):
        closer = getattr(stream, name, None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result
            return


class _GeminiStream:
    """genai 的流 + 它专用的客户端: 关流的时候一起关掉"""

    def __init__(self, inner: Any, client: genai.Client) -> None:
        self._inner = inner
        self._client = client

    def __aiter__(self) -> _GeminiStream:
        return self

    async def __anext__(self) -> Any:
        return await self._inner.__anext__()

    async def aclose(self) -> None:
        with contextlib.suppress(Exception):
            await _close_stream(self._inner)
        with contextlib.suppress(Exception):
            await self._client.aio.aclose()


@dataclass(frozen=True)
class Completion:
    text: str
    reasoning: str
    signature: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: FinishReason
    usage: Usage | None
    endpoint_id: str


@dataclass(frozen=True)
class EndpointStats:
    id: str
    protocol: str
    model: str
    calls: int
    failures: int
    latency_ms: float
    usage: Usage
    disabled: bool
    cooldown_s: float


def _check_sdk_env() -> None:
    offending = [
        name for name in (*_SDK_ENV_HEADERS, *_SDK_ENV_IDENTITY) if os.environ.get(name)
    ]
    if offending:
        raise LLMConfigError(
            "这些环境变量会被 SDK 自动加进请求头, 可能把凭据或组织信息发到配置之外的端点; "
            f"先 unset: {', '.join(offending)}"
        )


class _Endpoint:
    """单个端点的运行时状态"""

    def __init__(self, spec: EndpointSpec) -> None:
        self.spec = spec
        self.http = httpx2.AsyncClient(
            proxy=spec.proxy,
            # httpx2 要求四段超时全给, 否则拒绝构造
            timeout=httpx2.Timeout(
                connect=spec.connect_timeout,
                read=spec.timeout,
                write=spec.timeout,
                pool=spec.connect_timeout,
            ),
            limits=httpx2.Limits(
                max_connections=max(1, spec.max_concurrency),
                max_keepalive_connections=max(1, spec.max_concurrency),
            ),
        )
        # 两个 SDK 的客户端类型互不相干, 按协议分派调用, 这里只当传输层用
        self.client: Any = self._make_client()
        self.semaphore = asyncio.Semaphore(max(1, spec.max_concurrency))
        self.failures = 0
        self.cooldown_until = 0.0
        self.disabled_reason: str | None = None
        self.latency_ms = 0.0
        self.calls = 0
        self.usage = Usage()

    def _make_client(self) -> Any:
        headers = {"User-Agent": DEFAULT_USER_AGENT, **self.spec.extra_headers}
        if self.spec.protocol == "gemini":
            # genai 的 http_options 只能在构造时给, 而会话头是逐请求的,
            # 所以这条路线每次请求现建一个客户端, 跟着流一起关 (见 gemini_client)
            return None
        # 永远显式传 key: openai 缺 key 会直接抛, anthropic 会去读 ANTHROPIC_API_KEY
        common: dict[str, Any] = {
            "api_key": self.spec.api_key or "none",
            "base_url": self.spec.base_url,
            "max_retries": 0,  # 重试由池子接管
            "default_headers": headers,
            "http_client": self.http,
        }
        if self.spec.protocol == "anthropic":
            return anthropic.AsyncAnthropic(**common)
        return openai.AsyncOpenAI(**common)

    def gemini_client(self, headers: Mapping[str, str]) -> genai.Client:
        """按请求头现建一个 genai 客户端: 聚合站要求的会话头只能这样带"""
        return genai.Client(
            api_key=self.spec.api_key or "none",
            http_options=genai_types.HttpOptions(
                base_url=self.spec.base_url,
                api_version="v1beta",
                headers={
                    "Authorization": f"Bearer {self.spec.api_key or 'none'}",
                    "User-Agent": DEFAULT_USER_AGENT,
                    **self.spec.extra_headers,
                    **headers,
                },
                timeout=int(self.spec.timeout * 1000),
            ),
        )

    async def aclose(self) -> None:
        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.close()
        with contextlib.suppress(Exception):
            await self.http.aclose()

    @property
    def disabled(self) -> bool:
        return self.disabled_reason is not None

    def available(self, now: float) -> bool:
        return not self.disabled and now >= self.cooldown_until

    def report_success(self, elapsed_ms: float, usage: Usage | None) -> None:
        self.failures = 0
        self.cooldown_until = 0.0
        self.calls += 1
        self.latency_ms = (
            elapsed_ms
            if not self.latency_ms
            else self.latency_ms * 0.8 + elapsed_ms * 0.2
        )
        if usage is not None:
            # 这里是跨请求累计, 不能用 merged (那个取的是流式分片之间的较大值)
            self.usage = self.usage.plus(usage)

    def report_failure(self, exc: LLMError) -> None:
        now = time.monotonic()
        if isinstance(exc, AuthError):
            self.disabled_reason = f"{exc.kind}: {exc}"
            self.cooldown_until = now + AUTH_COOLDOWN
            return
        if isinstance(exc, StreamAborted):
            # 截断与流内报错说明这个端点这一次不可靠, 短暂绕开, 不要永久惩罚
            self.failures += 1
            self.cooldown_until = now + min(2.0**self.failures, ABORT_COOLDOWN_CAP)
            return
        if isinstance(exc, RequestRejected) and exc.capability:
            # 参数不被支持是请求形状与端点不匹配, 端点本身还是健康的, 不冷却
            self.failures += 1
            return
        if exc.retryable:
            self.failures += 1
            retry_after = getattr(exc, "retry_after", None)
            delay = (
                float(retry_after)
                if retry_after
                else min(2.0**self.failures, COOLDOWN_CAP)
            )
            self.cooldown_until = now + delay

    def stats(self, now: float) -> EndpointStats:
        return EndpointStats(
            id=self.spec.id,
            protocol=self.spec.protocol,
            model=self.spec.model,
            calls=self.calls,
            failures=self.failures,
            latency_ms=round(self.latency_ms, 1),
            usage=self.usage,
            disabled=self.disabled,
            cooldown_s=round(max(0.0, self.cooldown_until - now), 1),
        )


class Pool:
    """一组端点 + 别名到端点列表的映射"""

    def __init__(
        self,
        endpoints: Sequence[EndpointSpec],
        aliases: Mapping[str, Sequence[str]],
        *,
        default_alias: str | None = None,
        max_attempts: int = 2,
    ) -> None:
        if not endpoints:
            raise LLMConfigError("至少需要一个端点")
        _check_sdk_env()
        self._eps: dict[str, _Endpoint] = {
            spec.id: _Endpoint(spec) for spec in endpoints
        }
        unknown = {name for ids in aliases.values() for name in ids} - set(self._eps)
        if unknown:
            raise LLMConfigError(
                f"别名里引用了不存在的端点: {', '.join(sorted(unknown))}"
            )
        self._aliases = {name: tuple(ids) for name, ids in aliases.items()}
        if not self._aliases:
            self._aliases = {"default": tuple(self._eps)}
        self._default_alias = default_alias or next(iter(self._aliases))
        if self._default_alias not in self._aliases:
            raise LLMConfigError(f"默认别名 {self._default_alias!r} 不在 aliases 里")
        self._max_attempts = max(1, max_attempts)
        self._cursor = dict.fromkeys(self._aliases, 0)

    @classmethod
    def from_settings(cls, settings: LLMSettings) -> Pool:
        specs = build_specs(settings)
        return cls(
            list(specs.values()),
            settings.aliases,
            default_alias=settings.default_alias,
            max_attempts=settings.max_attempts,
        )

    async def aclose(self) -> None:
        for endpoint in self._eps.values():
            await endpoint.aclose()

    async def __aenter__(self) -> Pool:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def stats(self) -> list[EndpointStats]:
        now = time.monotonic()
        return [endpoint.stats(now) for endpoint in self._eps.values()]

    # -- 端点选择 ----------------------------------------------------------
    def _alias_ids(self, alias: str | None) -> tuple[str, ...]:
        name = alias or self._default_alias
        try:
            return self._aliases[name]
        except KeyError:
            raise LLMConfigError(f"未知模型别名 {name!r}") from None

    def _pick(self, alias: str, ids: Sequence[str], tried: set[str]) -> _Endpoint:
        now = time.monotonic()
        fresh = [
            self._eps[i] for i in ids if i not in tried and self._eps[i].available(now)
        ]
        if not fresh:
            fresh = [self._eps[i] for i in ids if self._eps[i].available(now)]
        if not fresh:
            # 全部在冷却: 取冷却最早结束的那个硬着头皮试, 而不是直接报错
            candidates = [self._eps[i] for i in ids if not self._eps[i].disabled]
            if not candidates:
                raise LLMConfigError(f"别名 {alias!r} 下没有可用端点")
            return min(candidates, key=lambda e: e.cooldown_until)
        cursor = self._cursor.get(alias, 0) % len(fresh)
        self._cursor[alias] = cursor + 1
        return fresh[cursor]

    def _should_retry(self, exc: LLMError, *, started: bool, attempts: int) -> bool:
        if started or attempts >= self._max_attempts:
            return False
        if isinstance(exc, (StreamAborted, LLMConfigError)):
            return False
        # 鉴权失败说明这个端点不该再用, 但没道理让整个请求跟着失败
        if exc.disable_endpoint:
            return True
        if exc.retryable:
            return True
        return isinstance(exc, RequestRejected) and exc.capability

    # -- 调用 --------------------------------------------------------------
    async def _run(
        self,
        endpoint: _Endpoint,
        request: CompletionRequest,
        acc: StreamAccumulator,
        headers: Mapping[str, str],
    ) -> AsyncGenerator[StreamEvent, None]:
        spec = endpoint.spec
        module = protocols.for_protocol(spec.protocol)
        translation = module.build(request, model=spec.model, quirks=spec.quirks)
        body, dropped = translation.body, translation.dropped
        if dropped:
            message = f"端点 {spec.id} 丢弃了不支持的参数: {', '.join(dropped)}"
            if spec.strict_params:
                raise LLMConfigError(message)
            logger.debug(message)
        # SDK 的原生签名里没有的字段只能走 extra_body, 不能当关键字参数展开
        extra = {**translation.extra, **dict(spec.extra_body)}

        async with endpoint.semaphore:
            try:
                stream = await self._create(endpoint, body, extra, headers)
            except _SDK_ERRORS as exc:
                raise map_sdk_error(exc, endpoint_id=spec.id) from exc
            except LLMError:
                raise
            except (TypeError, ValueError) as exc:
                raise LLMConfigError(
                    f"端点 {spec.id} 的参数不被 SDK 接受: {exc}"
                ) from exc
            try:
                async for obj in stream:
                    for event in module.parse(obj, acc):
                        acc.observe(event)
                        yield event
            except _SDK_ERRORS as exc:
                raise map_sdk_error(exc, endpoint_id=spec.id) from exc
            finally:
                # 取消时也要把底层连接关掉, 而且不能被这次的取消打断
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await _close_stream(stream)

        completed = acc.completed(spec.id)
        yield completed

    async def _create(
        self,
        endpoint: _Endpoint,
        body: dict[str, Any],
        extra: dict[str, Any],
        headers: Mapping[str, str],
    ):
        spec = endpoint.spec
        if spec.protocol == "gemini":
            client = endpoint.gemini_client(headers)
            # genai 的流式调用本身就是可等待的, 拿到的是异步迭代器;
            # 客户端跟着流一起关, 否则每轮请求都会漏一个连接池
            try:
                inner = await client.aio.models.generate_content_stream(
                    model=body["model"],
                    contents=body["contents"],
                    config=body["config"],
                )
            except _SDK_ERRORS:
                with contextlib.suppress(Exception):
                    await client.aio.aclose()
                raise
            return _GeminiStream(inner, client)
        kwargs = {
            **body,
            "extra_body": extra,
            "extra_headers": dict(headers),
        }
        if spec.protocol == "anthropic":
            return await endpoint.client.messages.create(**kwargs)
        if spec.protocol == "chat":
            return await endpoint.client.chat.completions.create(**kwargs)
        return await endpoint.client.responses.create(**kwargs)

    async def stream(
        self,
        request: CompletionRequest,
        *,
        alias: str | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        alias_name = alias or self._default_alias
        ids = self._alias_ids(alias_name)
        # 一次逻辑请求固定同一个幂等键, 换端点也不能换
        idempotency = uuid.uuid4().hex
        tried: set[str] = set()
        attempts = 0
        last: LLMError | None = None

        while attempts < self._max_attempts:
            attempts += 1
            endpoint = self._pick(alias_name, ids, tried)
            tried.add(endpoint.spec.id)
            headers = {"Idempotency-Key": idempotency}
            if endpoint.spec.session_header and session_id:
                headers[endpoint.spec.session_header] = session_id
            acc = StreamAccumulator()
            started = False
            began = time.monotonic()
            try:
                async with contextlib.aclosing(
                    self._run(endpoint, request, acc, headers)
                ) as events:
                    async for event in events:
                        started = True
                        yield event
            except LLMError as exc:
                endpoint.report_failure(exc)
                last = exc
                if started and not isinstance(exc, StreamAborted):
                    # 内容已经吐出去了, 这时候只能把残片交代清楚, 不能重来
                    raise StreamAborted(
                        f"{exc.kind}: {exc}",
                        partial=acc.partial(),
                        endpoint_id=endpoint.spec.id,
                    ) from exc
                if self._should_retry(exc, started=started, attempts=attempts):
                    logger.warning(
                        "端点 %s 失败 (%s), 换下一个端点重试: %s",
                        endpoint.spec.id,
                        exc.kind,
                        exc,
                    )
                    continue
                raise
            else:
                endpoint.report_success((time.monotonic() - began) * 1000, acc.usage)
                return

        raise last or LLMConfigError("所有端点都失败了")

    async def complete(
        self,
        request: CompletionRequest,
        *,
        alias: str | None = None,
        session_id: str | None = None,
    ) -> Completion:
        text: list[str] = []
        reasoning: list[str] = []
        signature: list[str] = []
        completed: Completed | None = None
        async for event in self.stream(request, alias=alias, session_id=session_id):
            if isinstance(event, TextDelta):
                text.append(event.text)
            elif isinstance(event, ReasoningDelta):
                reasoning.append(event.text)
            elif isinstance(event, SignatureDelta):
                signature.append(event.signature)
            elif isinstance(event, Completed):
                completed = event
        if completed is None:  # 流异常结束时本该抛异常, 这里是兜底
            raise LLMConfigError("流没有产出 Completed 事件")
        return Completion(
            text="".join(text),
            reasoning="".join(reasoning),
            signature="".join(signature),
            tool_calls=completed.tool_calls,
            finish_reason=completed.finish_reason,
            usage=completed.usage,
            endpoint_id=completed.endpoint_id,
        )
