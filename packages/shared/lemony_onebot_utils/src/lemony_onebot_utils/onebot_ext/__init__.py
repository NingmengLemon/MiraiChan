"""实现端扩展的 OneBot 11 兼容层

melobot 只内置标准 action, 而实现端 (SnowLuma / NapCat / Lagrange) 各自加了一批。这个包把它们
收在一个地方:

- :mod:`catalog`: 收录清单, 每个条目写清 kind、参数/字段、有证据支持的实现端与来源
- :mod:`actions`: 已收录 action 的类型化封装, 关键字参数, 不手写 ``{"action": ...}``
- :mod:`events`: 扩展事件载荷的解析函数 (贴表情回应、bot 自己发的消息)
- :mod:`base`: :class:`ExtensionAction` 与 :func:`call_extension` / :func:`try_extension`

用法::

    from lemony_onebot_utils.onebot_ext import SetMsgEmojiLike, try_extension

    await try_extension(adapter, SetMsgEmojiLike(message_id=event.message_id, emoji_id="128308"))

这些 action 不是标准, 未必被实现端支持; 需要"不支持就退让"时用 ``try_extension``。
"""

from __future__ import annotations

from .actions import (
    DeleteEssenceMsg,
    FetchCustomFace,
    FetchCustomFaceEcho,
    FriendPoke,
    GetEssenceMsgList,
    GetEssenceMsgListEcho,
    GetFriendMsgHistory,
    GetGroupFilesByFolder,
    GetGroupFileUrl,
    GetGroupMsgHistory,
    GetGroupRootFiles,
    GroupPoke,
    HistoryEcho,
    SendPoke,
    SetEssenceMsg,
    SetGroupReaction,
    SetMsgEmojiLike,
    UploadGroupFile,
    UploadPrivateFile,
)
from .base import ExtensionAction, ExtensionError, call_extension, try_extension
from .catalog import EXTENSIONS, SPECS, ExtensionSpec, find, for_impl, load_entries
from .events import EmojiLike, GroupMsgEmojiLike, is_message_sent

__all__ = [
    "EXTENSIONS",
    "SPECS",
    "DeleteEssenceMsg",
    "EmojiLike",
    "ExtensionAction",
    "ExtensionError",
    "ExtensionSpec",
    "FetchCustomFace",
    "FetchCustomFaceEcho",
    "FriendPoke",
    "GetEssenceMsgList",
    "GetEssenceMsgListEcho",
    "GetFriendMsgHistory",
    "GetGroupFileUrl",
    "GetGroupFilesByFolder",
    "GetGroupMsgHistory",
    "GetGroupRootFiles",
    "GroupMsgEmojiLike",
    "GroupPoke",
    "HistoryEcho",
    "SendPoke",
    "SetEssenceMsg",
    "SetGroupReaction",
    "SetMsgEmojiLike",
    "UploadGroupFile",
    "UploadPrivateFile",
    "call_extension",
    "find",
    "for_impl",
    "is_message_sent",
    "load_entries",
    "try_extension",
]
