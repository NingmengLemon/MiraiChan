"""引用文档模型 (纯数据)。

消息来源 (recorder / get_msg) 先统一成 :class:`SourceMessage`, 再由 normalize
转成渲染用的 :class:`QuoteMessage`。渲染层只认这里的类型。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Element",
    "ImageElement",
    "ImageRef",
    "QuoteMessage",
    "SourceMessage",
    "SourceSegment",
    "TextElement",
]


@dataclass(frozen=True, slots=True)
class SourceSegment:
    type: str
    data: Mapping[str, Any]
    local_paths: tuple[str, ...] = ()
    """recorder 已下载的本地文件 (相对 data 根), 优先于 url"""


@dataclass(frozen=True, slots=True)
class SourceMessage:
    message_id: str
    sender_id: int
    sender_card: str | None
    sender_nickname: str | None
    segments: tuple[SourceSegment, ...]
    timestamp: float | None = None


@dataclass(frozen=True, slots=True)
class ImageRef:
    """一张待取的图: 本地路径优先, 其次 url"""

    url: str | None
    local_paths: tuple[str, ...] = ()
    is_mface: bool = False

    @property
    def key(self) -> str:
        return self.local_paths[0] if self.local_paths else (self.url or "")


@dataclass(frozen=True, slots=True)
class TextElement:
    text: str


@dataclass(frozen=True, slots=True)
class ImageElement:
    ref: ImageRef


Element = TextElement | ImageElement


@dataclass(frozen=True, slots=True)
class QuoteMessage:
    message_id: str
    sender_id: int
    display_name: str
    """群名片, 无群名片时为昵称, 都没有时为 QQ 号"""
    nickname: str | None
    card: str | None
    elements: tuple[Element, ...] = field(default=())

    @property
    def text(self) -> str:
        return "".join(e.text for e in self.elements if isinstance(e, TextElement))

    @property
    def images(self) -> tuple[ImageRef, ...]:
        return tuple(e.ref for e in self.elements if isinstance(e, ImageElement))
