"""消息来源: recorder 优先, 单条消息可回退到 OneBot get_msg。

这里不依赖 bot 上下文, recorder 服务与取消息的函数都由调用方注入, 便于测试。
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .model import SourceMessage, SourceSegment
from .request import ChatRequest

__all__ = [
    "FetchResult",
    "MessageFetcher",
    "RecorderLike",
    "fetch_messages",
    "source_from_onebot",
]


class _SegmentViewLike(Protocol):
    @property
    def type(self) -> str: ...
    @property
    def data(self) -> Mapping[str, Any]: ...
    @property
    def media_paths(self) -> tuple[str, ...]: ...


class _MessageViewLike(Protocol):
    @property
    def external_message_id(self) -> str: ...
    @property
    def sender_external_id(self) -> str: ...
    @property
    def sender_display_name(self) -> str | None: ...
    @property
    def sender_conversation_name(self) -> str | None: ...
    @property
    def segments(self) -> Sequence[_SegmentViewLike]: ...


class RecorderLike(Protocol):
    """mbplugin_recorder.service.RecorderService 的最小接口"""

    async def get_message_window(self, query: Any) -> Sequence[Any] | None: ...


MessageFetcher = Callable[[str], Awaitable[SourceMessage | None]]
"""按消息 id 现取一条消息 (get_msg), 取不到返回 None"""

QueryFactory = Callable[[ChatRequest, str], Any]
"""(请求, 基准消息 id) -> recorder 的 MessageWindowQuery"""


@dataclass(frozen=True, slots=True)
class FetchResult:
    messages: tuple[SourceMessage, ...]
    from_recorder: bool
    degraded_to_single: bool = False
    """请求的是区间, 但 recorder 里没有基准消息, 只能降级为单条"""


def _from_view(view: _MessageViewLike) -> SourceMessage:
    return SourceMessage(
        message_id=view.external_message_id,
        sender_id=int(view.sender_external_id),
        sender_card=view.sender_conversation_name,
        sender_nickname=view.sender_display_name,
        segments=tuple(
            SourceSegment(s.type, dict(s.data), tuple(s.media_paths))
            for s in view.segments
        ),
    )


def source_from_onebot(
    message_id: str,
    sender_id: int,
    card: str | None,
    nickname: str | None,
    segments: Sequence[Mapping[str, Any]],
) -> SourceMessage:
    """OneBot 段字典 (type + data) -> SourceMessage; card 等于 nickname 时当作没有群名片"""
    card = card or None
    if card is not None and card == nickname:
        card = None
    return SourceMessage(
        message_id=message_id,
        sender_id=sender_id,
        sender_card=card,
        sender_nickname=nickname or None,
        segments=tuple(
            SourceSegment(str(s.get("type", "")), dict(s.get("data") or {}))
            for s in segments
        ),
    )


async def fetch_messages(
    req: ChatRequest,
    base_message_id: str,
    *,
    recorder: RecorderLike | None,
    make_query: QueryFactory,
    fetch_one: MessageFetcher,
) -> FetchResult | None:
    """取引用所需的消息。取不到任何消息时返回 None"""
    if recorder is not None:
        views = await recorder.get_message_window(make_query(req, base_message_id))
        if views is not None:
            return FetchResult(
                tuple(_from_view(v) for v in views), from_recorder=True
            )
    one = await fetch_one(base_message_id)
    if one is None:
        return None
    if req.is_single:
        return FetchResult((one,), from_recorder=False)
    # 区间只有 recorder 能给。区间包含基准时降级为单条; 不包含基准时没有可降级的内容
    contains_base = req.start <= 0 <= req.end
    return FetchResult(
        (one,) if contains_base else (),
        from_recorder=False,
        degraded_to_single=True,
    )
