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

    对应 QQ 的"群消息被贴表情回应"。``sub_type`` 统一归一成 ``add`` 或 ``remove``:
    SnowLuma 直接给 ``sub_type``, NapCat 用 ``is_add``, 这里两种都认。
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
                emoji_id=str(item.get("emoji_id", "")), count=_int(item.get("count"))
            )
            for item in raw.get("likes") or ()
            if isinstance(item, dict)
        )
        return cls(
            group_id=_int(raw.get("group_id")),
            user_id=_int(raw.get("user_id")),
            operator_id=_int(raw.get("operator_id", raw.get("user_id"))),
            message_id=_int(raw.get("message_id")),
            sub_type=_sub_type(raw),
            likes=likes,
            message_seq=_int(raw.get("message_seq")) or None,
        )


def _sub_type(raw: dict[str, Any]) -> str:
    """SnowLuma 给 sub_type; NapCat 只给 is_add"""
    if isinstance(value := raw.get("sub_type"), str) and value:
        return value
    if "is_add" in raw:
        is_add = raw.get("is_add")
        return "add" if is_add is True or is_add == 1 else "remove"
    return ""


def _int(value: object) -> int:
    """载荷字段可能是数字或数字字符串, 缺失/畸形时退回 0, 不让事件解析炸掉"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def is_message_sent(raw: dict[str, Any]) -> bool:
    """bot 自己发出的消息: SnowLuma 用 ``post_type=message_sent``

    melobot 不把这种事件当消息事件, 需要读 ``event.raw``。
    """
    return raw.get("post_type") == "message_sent"
