"""协议翻译层的共用件"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import LLMConfigError
from ..models import CompletionRequest, ImagePart, Message
from ..quirks import Quirks


@dataclass(frozen=True)
class Translation:
    body: dict[str, Any]
    dropped: tuple[str, ...] = ()  # 因为端点不支持而丢掉的采样参数


def sendable_messages(request: CompletionRequest) -> list[Message]:
    return [m for m in request.messages if not m.is_empty_assistant()]


def has_images(request: CompletionRequest) -> bool:
    return any(
        isinstance(part, ImagePart)
        for message in request.messages
        for part in message.parts
    )


def check_capabilities(request: CompletionRequest, quirks: Quirks) -> None:
    """能力类参数缺支持就当场报错, 不能静默降级成普通文本"""
    if request.tools and not quirks.supports_tools:
        raise LLMConfigError("该端点不支持工具调用")
    if request.json_schema and not quirks.supports_json_schema:
        raise LLMConfigError("该端点不支持 JSON Schema 结构化输出")
    if has_images(request) and not quirks.supports_images:
        raise LLMConfigError("该端点不支持图片输入")


def select_stop(
    request: CompletionRequest, quirks: Quirks, dropped: list[str]
) -> list[str]:
    if not request.stop:
        return []
    if not quirks.supports_stop:
        dropped.append("stop")
        return []
    return list(request.stop)


def select_temperature(
    request: CompletionRequest, quirks: Quirks, dropped: list[str]
) -> float | None:
    if request.temperature is None:
        return None
    if not quirks.supports_temperature:
        dropped.append("temperature")
        return None
    return request.temperature


def select_top_p(
    request: CompletionRequest, quirks: Quirks, dropped: list[str]
) -> float | None:
    if request.top_p is None:
        return None
    if not quirks.supports_top_p:
        dropped.append("top_p")
        return None
    return request.top_p


def tool_choice_value(tool_choice: str | None, *, style: str) -> object | None:
    """把统一的 tool_choice 折成各协议的形状"""
    if tool_choice is None:
        return None
    if style == "chat":
        if tool_choice in {"auto", "none", "required"}:
            return tool_choice
        return {"type": "function", "function": {"name": tool_choice}}
    if style == "responses":
        if tool_choice in {"auto", "none", "required"}:
            return tool_choice
        return {"type": "function", "name": tool_choice}
    # anthropic
    return {
        "auto": {"type": "auto"},
        "none": {"type": "none"},
        "required": {"type": "any"},
    }.get(tool_choice, {"type": "tool", "name": tool_choice})
