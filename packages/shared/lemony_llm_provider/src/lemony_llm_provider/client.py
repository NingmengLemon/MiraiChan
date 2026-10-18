"""端点池: 多 key 轮询、冷却熔断、失败换端点、流式归一化"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import anthropic
import openai

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
# 鉴权错误的冷却时间: 基本等于"本进程内不再使用"
AUTH_COOLDOWN = 3600.0
# 端点要求客户端自报身份, 不要用 SDK 或 HTTP 库的默认 UA
DEFAULT_USER_AGENT = "miraichan-llm/0.1"


@dataclass(frozen=True)
class Completion:
    text: str
    reasoning: str
    signature: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: FinishReason
    usage: Usage | None
    endpoint_id: str


class _Endpoint:
    """单个端点的运行时状态"""

    def __init__(self, spec: EndpointSpec) -> None:
        self.spec = spec
        # 两个 SDK 的客户端类型互不相干, 按协议分派调用, 这里只当传输层用
        self.client: Any = self._make_client()
        self.semaphore = asyncio.Semaphore(max(1, spec.max_concurrency))
        self.failures = 0
        self.cooldown_until = 0.0
        self.disabled_reason: str | None = None
        self.latency_ms = 0.0
        self.calls = 0
        self.usage = Usage()

    def _make_client(self) -> openai.AsyncOpenAI | anthropic.AsyncAnthropic:
        headers = {"User-Agent": DEFAULT_USER_AGENT, **self.spec.extra_headers}
        # 永远显式传 key: openai 缺 key 会直接抛, anthropic 会去读 ANTHROPIC_API_KEY
        api_key = self.spec.api_key or "none"
        common: dict[str, Any] = {
            "api_key": api_key,
            "base_url": self.spec.base_url,
            "max_retries": 0,  # 重试由池子接管
            "timeout": self.spec.timeout,
            "default_headers": headers,
        }
        if self.spec.protocol == "anthropic":
            return anthropic.AsyncAnthropic(**common)
        return openai.AsyncOpenAI(**common)

    async def aclose(self) -> None:
        await self.client.close()

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
        if isinstance(exc, RequestRejected) and exc.capability:
            # 端点可能只是不支持这个参数, 短暂冷却后仍可服务别的请求
            self.failures += 1
            self.cooldown_until = now + COOLDOWN_CAP / 2
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
    def from_settings(
        cls,
        settings: LLMSettings,
        *,
        max_attempts: int = 2,
    ) -> Pool:
        specs = build_specs(settings)
        return cls(
            list(specs.values()),
            settings.aliases,
            default_alias=settings.default_alias,
            max_attempts=max_attempts,
        )

    async def aclose(self) -> None:
        for endpoint in self._eps.values():
            await endpoint.aclose()

    async def __aenter__(self) -> Pool:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

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
    ) -> AsyncIterator[StreamEvent]:
        spec = endpoint.spec
        module = protocols.for_protocol(spec.protocol)
        translation = module.build(request, model=spec.model, quirks=spec.quirks)
        body, dropped = translation.body, translation.dropped
        if dropped:
            message = f"端点 {spec.id} 丢弃了不支持的参数: {', '.join(dropped)}"
            if spec.strict_params:
                raise LLMConfigError(message)
            logger.debug(message)
        merged_body = {**body, **dict(spec.extra_body)}

        async with endpoint.semaphore:
            try:
                if spec.protocol == "anthropic":
                    stream = await endpoint.client.messages.create(
                        **merged_body, extra_headers=dict(headers)
                    )
                elif spec.protocol == "chat":
                    stream = await endpoint.client.chat.completions.create(
                        **merged_body, extra_headers=dict(headers)
                    )
                else:
                    stream = await endpoint.client.responses.create(
                        **merged_body, extra_headers=dict(headers)
                    )
                try:
                    async for obj in stream:
                        for event in module.parse(obj, acc):
                            acc.observe(event)
                            yield event
                finally:
                    await stream.close()
            except (openai.OpenAIError, anthropic.AnthropicError) as exc:
                raise map_sdk_error(exc, endpoint_id=spec.id) from exc

        completed = acc.completed(spec.id)
        yield completed

    async def stream(
        self,
        request: CompletionRequest,
        *,
        alias: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
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
                async for event in self._run(endpoint, request, acc, headers):
                    started = True
                    yield event
            except LLMError as exc:
                endpoint.report_failure(exc)
                last = exc
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
