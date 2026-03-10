from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from melobot.io import EchoPacket as RootEchoPak
from melobot.io import InPacket as RootInPak
from melobot.io import OutPacket as RootOutPak

from ..const import PROTOCOL_IDENTIFIER


@dataclass(kw_only=True)
class InPacket(RootInPak):  # type: ignore[override]
    """Telegram 输入包，data 为 aiogram Update 对象"""

    data: Any
    protocol: str = PROTOCOL_IDENTIFIER


@dataclass(kw_only=True)
class OutPacket(RootOutPak):  # type: ignore[override]
    """Telegram 输出包

    data 为 aiogram 的 API method 对象（如 SendMessage 等），
    由 OutputFactory 从 Action 创建。
    """

    data: Any  # aiogram method object
    protocol: str = PROTOCOL_IDENTIFIER


@dataclass(kw_only=True)
class EchoPacket(RootEchoPak):  # type: ignore[override]
    """Telegram 回应包"""

    data: Any = None
    protocol: str = PROTOCOL_IDENTIFIER
