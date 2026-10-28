"""扩展事件的小工具

melobot 对未知的 ``post_type`` / ``notice_type`` 会退化成通用事件并保留原始数据 (``event.raw``),
所以这里不重建事件类, 只提供解析函数, 把形状固定下来并挡住字段缺失。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["EmojiLike", "GroupMsgEmojiLike", "is_message_sent"]


@dataclass(frozen=True, slots=True)
class EmojiLike:
    emoji_id: str
    count: int


@dataclass(frozen=True, slots=True)
class GroupMsgEmojiLike:
    """``notice_type=group_msg_emoji_like`` 的载荷

    对应 QQ 的"群消息被贴表情回应"。``sub_type`` 为 ``add`` 或 ``remove``。
    """

    group_id: int
    user_id: int
    operator_id: int
    message_id: int
    sub_type: str
    likes: tuple[EmojiLike, ...]
    message_seq: int | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> GroupMsgEmojiLike | None:
        if raw.get("notice_type") != "group_msg_emoji_like":
            return None
        likes = tuple(
            EmojiLike(
                emoji_id=str(item.get("emoji_id", "")), count=int(item.get("count", 0))
            )
            for item in raw.get("likes") or ()
            if isinstance(item, dict)
        )
        return cls(
            group_id=int(raw.get("group_id", 0)),
            user_id=int(raw.get("user_id", 0)),
            operator_id=int(raw.get("operator_id", raw.get("user_id", 0))),
            message_id=int(raw.get("message_id", 0)),
            sub_type=str(raw.get("sub_type", "")),
            likes=likes,
            message_seq=(
                int(raw["message_seq"])
                if isinstance(raw.get("message_seq"), int)
                else None
            ),
        )


def is_message_sent(raw: dict[str, Any]) -> bool:
    """bot 自己发出的消息: SnowLuma 用 ``post_type=message_sent``

    melobot 不把这种事件当消息事件, 需要读 ``event.raw``。
    """
    return raw.get("post_type") == "message_sent"
