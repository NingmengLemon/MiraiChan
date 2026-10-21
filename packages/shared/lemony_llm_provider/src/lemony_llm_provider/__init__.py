"""纯异步多协议 LLM 访问层

对外只暴露 `Pool`: 按模型别名挑端点, 把各协议的流式事件归一化之后交出去。
详细设计见同目录的 design.md。
"""

from __future__ import annotations

from .agent import Agent, AgentAnswer, CompleteFn, Toolbox
from .client import COOLDOWN_CAP, DEFAULT_USER_AGENT, Completion, EndpointStats, Pool
from .errors import (
    AuthError,
    ConnectionFailed,
    LLMConfigError,
    LLMError,
    Overloaded,
    RateLimited,
    RequestRejected,
    StreamAborted,
    UpstreamServerError,
    UpstreamTimeout,
    map_sdk_error,
)
from .models import (
    Completed,
    CompletionRequest,
    Effort,
    FinishReason,
    ImagePart,
    Message,
    PartialOutput,
    Protocol,
    Reasoning,
    ReasoningDelta,
    SignatureDelta,
    StreamAccumulator,
    StreamEvent,
    TextDelta,
    TextPart,
    ToolCall,
    ToolCallArgsDelta,
    ToolCallStart,
    ToolSpec,
    Usage,
)
from .quirks import Quirks, preset_names, resolve_quirks
from .settings import EndpointSettings, EndpointSpec, LLMSettings, build_specs

__all__ = [
    "COOLDOWN_CAP",
    "DEFAULT_USER_AGENT",
    "Agent",
    "AgentAnswer",
    "AuthError",
    "CompleteFn",
    "Completed",
    "Completion",
    "CompletionRequest",
    "ConnectionFailed",
    "Effort",
    "EndpointSettings",
    "EndpointSpec",
    "EndpointStats",
    "FinishReason",
    "ImagePart",
    "LLMConfigError",
    "LLMError",
    "LLMSettings",
    "Message",
    "Overloaded",
    "PartialOutput",
    "Pool",
    "Protocol",
    "Quirks",
    "RateLimited",
    "Reasoning",
    "ReasoningDelta",
    "RequestRejected",
    "SignatureDelta",
    "StreamAborted",
    "StreamAccumulator",
    "StreamEvent",
    "TextDelta",
    "TextPart",
    "ToolCall",
    "ToolCallArgsDelta",
    "ToolCallStart",
    "ToolSpec",
    "Toolbox",
    "UpstreamServerError",
    "UpstreamTimeout",
    "Usage",
    "build_specs",
    "map_sdk_error",
    "preset_names",
    "resolve_quirks",
]
