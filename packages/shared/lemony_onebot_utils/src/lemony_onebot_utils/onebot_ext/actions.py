"""已收录的扩展 action

每个类只负责 action 名与参数形状, 发送与错误处理交给 :func:`~.base.call_extension`。
可选参数统一用 :func:`_compact` 丢掉 None, 避免把 ``null`` 发给实现端。
"""

from __future__ import annotations

from typing import Any, TypedDict, cast

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


def _compact(**kwargs: object) -> dict[str, object]:
    """丢掉值为 None 的参数; 实现端对多余 null 的容忍度不一致"""
    return {key: value for key, value in kwargs.items() if value is not None}


# ---------------------------------------------------------------- 表情回应


class SetMsgEmojiLike(ExtensionAction):
    """在消息上添加/移除表情回应

    ``emoji_id`` 的取值按字符串长度判定: 1-3 位数字是 QQ 系统表情编号, 4 位及以上是 Unicode 码位。
    """

    action_name = "set_msg_emoji_like"

    def __init__(self, *, message_id: int, emoji_id: str, set: bool = True) -> None:
        super().__init__(message_id=message_id, emoji_id=emoji_id, set=set)


class SetGroupReaction(ExtensionAction):
    """给群消息贴 QQ 表情

    ``code`` 与 ``set_msg_emoji_like`` 的 ``emoji_id`` 是同一套编号: 1-3 位数字是 QQ 表情编号,
    4 位及以上是 Unicode 码位。
    """

    action_name = "set_group_reaction"

    def __init__(
        self,
        *,
        message_id: int,
        code: str,
        group_id: int | None = None,
        is_set: bool = True,
    ) -> None:
        super().__init__(
            **_compact(
                message_id=message_id,
                code=code,
                group_id=group_id,
                is_set=is_set,
            )
        )


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
        super().__init__(
            **_compact(group_id=group_id, user_id=user_id, target_id=target_id)
        )


class SendPoke(ExtensionAction):
    action_name = "send_poke"

    def __init__(
        self,
        *,
        user_id: int | None = None,
        group_id: int | None = None,
        target_id: int | None = None,
    ) -> None:
        super().__init__(
            **_compact(user_id=user_id, group_id=group_id, target_id=target_id)
        )


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
        reverse_order: bool | None = None,
    ) -> None:
        super().__init__(
            **_compact(
                group_id=group_id,
                message_id=message_id,
                message_seq=message_seq,
                count=count,
                reverse_order=reverse_order,
            )
        )


class GetFriendMsgHistory(ExtensionAction):
    action_name = "get_friend_msg_history"

    def __init__(
        self,
        *,
        user_id: int,
        message_id: int | None = None,
        message_seq: int | None = None,
        count: int = 20,
        reverse_order: bool | None = None,
    ) -> None:
        super().__init__(
            **_compact(
                user_id=user_id,
                message_id=message_id,
                message_seq=message_seq,
                count=count,
                reverse_order=reverse_order,
            )
        )


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
        self,
        *,
        group_id: int,
        file: str,
        name: str,
        folder: str | None = None,
        folder_id: str | None = None,
        upload_file: bool | None = None,
    ) -> None:
        super().__init__(
            **_compact(
                group_id=group_id,
                file=file,
                name=name,
                folder=folder,
                folder_id=folder_id,
                upload_file=upload_file,
            )
        )


class UploadPrivateFile(ExtensionAction):
    action_name = "upload_private_file"

    def __init__(self, *, user_id: int, file: str, name: str) -> None:
        super().__init__(user_id=user_id, file=file, name=name)


class CreateGroupFileFolder(ExtensionAction):
    action_name = "create_group_file_folder"

    def __init__(
        self, *, group_id: int, name: str, parent_id: str | None = None
    ) -> None:
        super().__init__(**_compact(group_id=group_id, name=name, parent_id=parent_id))


class GetGroupRootFiles(ExtensionAction):
    action_name = "get_group_root_files"

    def __init__(self, *, group_id: int, file_count: int | None = None) -> None:
        super().__init__(**_compact(group_id=group_id, file_count=file_count))


class GetGroupFilesByFolder(ExtensionAction):
    action_name = "get_group_files_by_folder"

    def __init__(
        self,
        *,
        group_id: int,
        folder_id: str | None = None,
        folder: str | None = None,
        file_count: int | None = None,
    ) -> None:
        super().__init__(
            **_compact(
                group_id=group_id,
                folder_id=folder_id,
                folder=folder,
                file_count=file_count,
            )
        )


class GetGroupFileUrl(ExtensionAction):
    action_name = "get_group_file_url"

    def __init__(
        self, *, group_id: int, file_id: str, busid: int | None = None
    ) -> None:
        super().__init__(**_compact(group_id=group_id, file_id=file_id, busid=busid))


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
        for msg in cast(list[dict[str, Any]], self.data):
            content = msg.get("content") or []
            msg["content"] = [
                Segment.resolve(seg["type"], seg["data"]) for seg in content
            ]


# ---------------------------------------------------------------- 自定义表情


class FetchCustomFace(ExtensionAction):
    action_name = "fetch_custom_face"


class FetchCustomFaceEcho(Echo):
    data: list[str] | None


# adapter 只按标准 action 名分派 echo, 这些专用回应由 call_extension 组装
GetGroupMsgHistory.echo_cls = HistoryEcho
GetFriendMsgHistory.echo_cls = HistoryEcho
GetEssenceMsgList.echo_cls = GetEssenceMsgListEcho
FetchCustomFace.echo_cls = FetchCustomFaceEcho
