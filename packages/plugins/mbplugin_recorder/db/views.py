"""面向其他插件的只读视图。

查询结果在 session 内完整取出后转成这些不可变 dataclass, 调用方不接触 ORM 对象,
也不会在 session 关闭后触发懒加载。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = ["MessageView", "MessageWindowQuery", "SegmentView"]


@dataclass(frozen=True, slots=True)
class SegmentView:
    order: int
    type: str
    data: Mapping[str, Any]
    # 该段关联的、已下载完成的媒体本地路径 (recorder 写入时的原样字符串)
    media_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MessageView:
    external_message_id: str
    sender_external_id: str
    sender_display_name: str | None
    sender_conversation_name: str | None
    sent_at: datetime
    # 相对基准消息的偏移, 基准为 0, 更早为负
    offset: int
    segments: tuple[SegmentView, ...]


@dataclass(slots=True)
class MessageWindowQuery:
    """以基准消息为 0 的相对闭区间 [start, end] 取消息, 端点可以同号 (例如 -5..-2)。

    sender_only 为真时只计入与基准消息同一发送者的消息, 偏移也只在这些消息里数。
    """

    account_protocol: str
    account_self_id: str
    conversation_type: str
    conversation_external_id: str
    base_external_message_id: str
    start: int = 0
    end: int = 0
    sender_only: bool = False
    # 这些发送者的消息不计入窗口, 偏移也不数它们; 基准消息本身属于其中时结果为空
    exclude_sender_external_ids: tuple[str, ...] = ()
