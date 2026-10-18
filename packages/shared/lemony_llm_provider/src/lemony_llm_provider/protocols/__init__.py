"""三套协议的翻译与解析

每个协议模块都提供 `build(request, model=..., quirks=...) -> Translation` 与
`parse(obj, acc) -> list[StreamEvent]`。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..models import StreamAccumulator, StreamEvent
from . import anthropic, chat, responses
from .base import Translation


@dataclass(frozen=True)
class ProtocolModule:
    build: Callable[..., Translation]
    parse: Callable[[Any, StreamAccumulator], list[StreamEvent]]


_BY_PROTOCOL: dict[str, ProtocolModule] = {
    "chat": ProtocolModule(chat.build, chat.parse),
    "responses": ProtocolModule(responses.build, responses.parse),
    "anthropic": ProtocolModule(anthropic.build, anthropic.parse),
}


def for_protocol(protocol: str) -> ProtocolModule:
    try:
        return _BY_PROTOCOL[protocol]
    except KeyError:
        raise ValueError(f"未知协议 {protocol!r}") from None


__all__ = [
    "ProtocolModule",
    "Translation",
    "anthropic",
    "chat",
    "for_protocol",
    "responses",
]
