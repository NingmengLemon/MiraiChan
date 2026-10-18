"""错误层级: 把两个 SDK 的异常折叠成调用方需要区分的几类

流已经打开之后 HTTP status 不可信(Anthropic 的流内错误挂在 200 响应上),
所以分类同时看异常类型与所处阶段, 不只看 status。
"""

from __future__ import annotations

import anthropic
import openai

from .models import PartialOutput

# 参数不被支持的典型说法, 用来把"换一个端点就能过"和"请求本身非法"分开
_CAPABILITY_HINTS = (
    "unsupported",
    "not supported",
    "does not support",
    "unknown parameter",
    "unrecognized request argument",
    "extra inputs are not permitted",
    "unexpected keyword",
    "invalid value for",
)


class LLMError(Exception):
    """所有错误的基类"""

    kind = "unknown"
    retryable = False
    # 鉴权错误: 这个端点不必再试, 换下一个
    disable_endpoint = False

    def __init__(
        self,
        message: str,
        *,
        endpoint_id: str | None = None,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.endpoint_id = endpoint_id
        self.status = status
        self.body = body


class LLMConfigError(LLMError):
    """配置或参数组合本身不合法, 换端点也没用"""

    kind = "config"


class AuthError(LLMError):
    kind = "auth"
    disable_endpoint = True


class RateLimited(LLMError):
    kind = "rate_limit"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kw) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class Overloaded(LLMError):
    kind = "overloaded"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kw) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class UpstreamTimeout(LLMError):
    kind = "timeout"
    retryable = True


class ConnectionFailed(LLMError):
    kind = "connection"
    retryable = True


class UpstreamServerError(LLMError):
    kind = "server"
    retryable = True


class RequestRejected(LLMError):
    """请求被拒。capability=True 表示问题可能只是这个端点不支持, 换一个也许能过"""

    kind = "rejected"

    def __init__(self, message: str, *, capability: bool = False, **kw) -> None:
        super().__init__(message, **kw)
        self.capability = capability


class StreamAborted(LLMError):
    """流中途结束: 断流、流内报错或上游失败。已经下发的部分放在 partial 里"""

    kind = "aborted"

    def __init__(self, message: str, *, partial: PartialOutput, **kw) -> None:
        super().__init__(message, **kw)
        self.partial = partial


def looks_like_capability_mismatch(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _CAPABILITY_HINTS)


def _retry_after(headers: object) -> float | None:
    try:
        raw = getattr(headers, "get", lambda _k: None)("retry-after")
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _headers_of(exc: Exception) -> object | None:
    return getattr(getattr(exc, "response", None), "headers", None)


def _message_of(exc: Exception) -> str:
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        return message
    return str(exc)


def _body_of(exc: Exception) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, str):
        return body[:2000]
    if body is None:
        return None
    return str(body)[:2000]


def map_sdk_error(exc: Exception, *, endpoint_id: str) -> LLMError:
    """把 openai / anthropic 的异常折叠成 LLMError 层级"""
    common = {
        "endpoint_id": endpoint_id,
        "status": getattr(exc, "status_code", None),
        "body": _body_of(exc),
    }
    message = _message_of(exc)
    retry_after = _retry_after(_headers_of(exc))

    if isinstance(exc, (openai.AuthenticationError, anthropic.AuthenticationError)):
        return AuthError(message, **common)
    if isinstance(exc, (openai.PermissionDeniedError, anthropic.PermissionDeniedError)):
        return AuthError(message, **common)
    if isinstance(exc, (openai.RateLimitError, anthropic.RateLimitError)):
        return RateLimited(message, retry_after=retry_after, **common)
    if isinstance(exc, (anthropic.OverloadedError, anthropic.ServiceUnavailableError)):
        return Overloaded(message, retry_after=retry_after, **common)
    if isinstance(exc, (openai.APITimeoutError, anthropic.APITimeoutError)):
        return UpstreamTimeout(message, **common)
    if isinstance(exc, (openai.APIConnectionError, anthropic.APIConnectionError)):
        return ConnectionFailed(message, **common)
    if isinstance(exc, (openai.InternalServerError, anthropic.InternalServerError)):
        return UpstreamServerError(message, **common)
    if isinstance(exc, (anthropic.DeadlineExceededError, anthropic.RetryableError)):
        return Overloaded(message, retry_after=retry_after, **common)
    if isinstance(exc, (openai.BadRequestError, anthropic.BadRequestError)):
        return RequestRejected(
            message, capability=looks_like_capability_mismatch(message), **common
        )
    if isinstance(
        exc, (openai.UnprocessableEntityError, anthropic.UnprocessableEntityError)
    ):
        return RequestRejected(
            message, capability=looks_like_capability_mismatch(message), **common
        )
    if isinstance(exc, (openai.APIStatusError, anthropic.APIStatusError)):
        status = common["status"]
        if status == 429:
            return RateLimited(message, retry_after=retry_after, **common)
        if status in (401, 403):
            return AuthError(message, **common)
        if status is not None and status >= 500:
            return UpstreamServerError(message, **common)
        return RequestRejected(
            message, capability=looks_like_capability_mismatch(message), **common
        )
    return LLMError(message, **common)
