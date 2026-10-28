"""已收录的扩展 action

每个类只负责 action 名与参数形状, 发送与错误处理交给 :func:`~.base.call_extension`。
"""

from __future__ import annotations

from typing import Any, TypedDict

from melobot.protocols.onebot.v11.adapter.echo import Echo
from melobot.protocols.onebot.v11.adapter.segment import Segment

from .base import ExtensionAction

__all__ = [
    "CreateGroupFileFolder",
    "DeleteEssenceMsg",
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
    "GroupPoke",
    "HistoryEcho",
    "SendPoke",
    "SetEssenceMsg",
    "SetGroupReaction",
    "SetMsgEmojiLike",
    "UploadGroupFile",
    "UploadPrivateFile",
]


# ---------------------------------------------------------------- 表情回应


class SetMsgEmojiLike(ExtensionAction):
    """在消息上添加/移除表情回应

    ``emoji_id`` 的取值按长度判定: 1-3 位数字是 QQ 系统表情编号, 4 位及以上是 Unicode 码位。
    """

    action_name = "set_msg_emoji_like"

    def __init__(self, *, message_id: int, emoji_id: str, set: bool = True) -> None:
        super().__init__(message_id=message_id, emoji_id=emoji_id, set=set)


class SetGroupReaction(ExtensionAction):
    """给群消息贴 QQ 表情; ``code`` 是表情编号 (如 ``"76"``), 和 emoji 码位不是一套"""

    action_name = "set_group_reaction"

    def __init__(
        self,
        *,
        message_id: int,
        code: str,
        group_id: int | None = None,
        is_set: bool = True,
    ) -> None:
        params: dict[str, Any] = {
            "message_id": message_id,
            "code": code,
            "is_set": is_set,
        }
        if group_id is not None:
            params["group_id"] = group_id
        super().__init__(**params)


# ---------------------------------------------------------------- 拍一拍


class FriendPoke(ExtensionAction):
    action_name = "friend_poke"

    def __init__(self, *, user_id: int) -> None:
        super().__init__(user_id=user_id)


class GroupPoke(ExtensionAction):
    action_name = "group_poke"

    def __init__(
        self, *, group_id: int, user_id: int | None = None, target_id: int | None = None
    ) -> None:
        params: dict[str, Any] = {"group_id": group_id}
        if user_id is not None:
            params["user_id"] = user_id
        if target_id is not None:
            params["target_id"] = target_id
        super().__init__(**params)


class SendPoke(ExtensionAction):
    action_name = "send_poke"

    def __init__(
        self,
        *,
        user_id: int | None = None,
        group_id: int | None = None,
        target_id: int | None = None,
    ) -> None:
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        if group_id is not None:
            params["group_id"] = group_id
        if target_id is not None:
            params["target_id"] = target_id
        super().__init__(**params)


# ---------------------------------------------------------------- 历史消息


class GetGroupMsgHistory(ExtensionAction):
    action_name = "get_group_msg_history"

    def __init__(
        self,
        *,
        group_id: int,
        message_id: int | None = None,
        message_seq: int | None = None,
        count: int = 20,
        reverse_order: bool = False,
    ) -> None:
        params: dict[str, Any] = {"group_id": group_id, "count": count}
        if message_id is not None:
            params["message_id"] = message_id
        if message_seq is not None:
            params["message_seq"] = message_seq
        if reverse_order:
            params["reverse_order"] = True
        super().__init__(**params)


class GetFriendMsgHistory(ExtensionAction):
    action_name = "get_friend_msg_history"

    def __init__(
        self,
        *,
        user_id: int,
        message_id: int | None = None,
        message_seq: int | None = None,
        count: int = 20,
        reverse_order: bool = False,
    ) -> None:
        params: dict[str, Any] = {"user_id": user_id, "count": count}
        if message_id is not None:
            params["message_id"] = message_id
        if message_seq is not None:
            params["message_seq"] = message_seq
        if reverse_order:
            params["reverse_order"] = True
        super().__init__(**params)


class HistoryEcho(Echo):
    """历史消息回应: ``data.messages`` 是消息事件形状的列表"""

    @property
    def messages(self) -> list[dict[str, Any]]:
        if isinstance(self.data, dict) and isinstance(self.data.get("messages"), list):
            return self.data["messages"]
        return []


# ---------------------------------------------------------------- 群文件


class UploadGroupFile(ExtensionAction):
    action_name = "upload_group_file"

    def __init__(
        self, *, group_id: int, file: str, name: str, folder: str | None = None
    ) -> None:
        params: dict[str, Any] = {"group_id": group_id, "file": file, "name": name}
        if folder is not None:
            params["folder"] = folder
        super().__init__(**params)


class UploadPrivateFile(ExtensionAction):
    action_name = "upload_private_file"

    def __init__(self, *, user_id: int, file: str, name: str) -> None:
        super().__init__(user_id=user_id, file=file, name=name)


class CreateGroupFileFolder(ExtensionAction):
    action_name = "create_group_file_folder"

    def __init__(self, *, group_id: int, name: str, parent_id: str) -> None:
        super().__init__(group_id=group_id, name=name, parent_id=parent_id)


class GetGroupRootFiles(ExtensionAction):
    action_name = "get_group_root_files"

    def __init__(self, *, group_id: int) -> None:
        super().__init__(group_id=group_id)


class GetGroupFilesByFolder(ExtensionAction):
    action_name = "get_group_files_by_folder"

    def __init__(self, *, group_id: int, folder_id: str) -> None:
        super().__init__(group_id=group_id, folder_id=folder_id)


class GetGroupFileUrl(ExtensionAction):
    action_name = "get_group_file_url"

    def __init__(self, *, group_id: int, file_id: str, busid: int) -> None:
        super().__init__(group_id=group_id, file_id=file_id, busid=busid)


# ---------------------------------------------------------------- 精华消息


class SetEssenceMsg(ExtensionAction):
    action_name = "set_essence_msg"

    def __init__(self, *, message_id: int) -> None:
        super().__init__(message_id=message_id)


class DeleteEssenceMsg(ExtensionAction):
    action_name = "delete_essence_msg"

    def __init__(self, *, message_id: int) -> None:
        super().__init__(message_id=message_id)


class GetEssenceMsgList(ExtensionAction):
    action_name = "get_essence_msg_list"

    def __init__(self, *, group_id: int) -> None:
        super().__init__(group_id=group_id)


class _EssenceMsg(TypedDict):
    sender_id: int
    sender_nick: str
    sender_time: int
    operator_id: int
    operator_nick: str
    operator_time: int
    message_id: int


class _EssenceMsgResolved(_EssenceMsg):
    content: list[Segment]


class GetEssenceMsgListEcho(Echo):
    """精华消息回应; ``content`` 里的消息段已解析成 :class:`Segment`"""

    data: list[_EssenceMsgResolved] | None

    def __init__(self, **kv_pairs: Any) -> None:
        super().__init__(**kv_pairs)
        if self.data is None:
            return
        raw: list[dict[str, Any]] = kv_pairs["data"]
        for msg in raw:
            msg["content"] = [
                Segment.resolve(seg["type"], seg["data"]) for seg in msg["content"]
            ]


# ---------------------------------------------------------------- 自定义表情


class FetchCustomFace(ExtensionAction):
    action_name = "fetch_custom_face"

    def __init__(self) -> None:
        super().__init__()


class FetchCustomFaceEcho(Echo):
    data: list[str] | None
