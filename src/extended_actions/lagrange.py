from typing import Any, Literal, NotRequired, Self, TypedDict, Unpack

from melobot.protocols.onebot.v11.adapter.action import Action
from melobot.protocols.onebot.v11.adapter.echo import Echo
from melobot.protocols.onebot.v11.adapter.segment import Segment
from pydantic import BaseModel


class FriendPokeAction(Action):
    def __init__(self, user_id: int):
        super().__init__("friend_poke", {"user_id": user_id})


class GroupPokeAction(Action):
    class Params(TypedDict):
        user_id: int
        group_id: int

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("group_poke", kwargs)


class FetchCustomFaceAction(Action):
    def __init__(self):
        super().__init__("fetch_custom_face", {})


class FetchCustomFaceEcho(Echo):
    class Model(Echo.Model):
        data: list[str] | None

    data: list[str] | None


class GetFriendMsgHistoryAction(Action):
    class Params(TypedDict):
        user_id: int
        message_id: int
        count: int

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("get_friend_msg_history", kwargs)


class GetGroupMsgHistoryAction(Action):
    class Params(TypedDict):
        group_id: int
        message_id: int
        count: int

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("get_group_msg_history", kwargs)


class UploadGroupFileAction(Action):
    class Params(TypedDict):
        group_id: int
        file: str
        name: str
        folder: NotRequired[str]

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("upload_group_file", kwargs)


class UploadPrivateFileAction(Action):
    class Params(TypedDict):
        user_id: int
        file: str
        name: str

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("upload_private_file", kwargs)


class CreateGroupFileFolderAction(Action):
    class Params(TypedDict):
        group_id: int
        name: str
        parent_id: str

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("create_group_file_folder", kwargs)


class GetGroupRootFilesAction(Action):
    def __init__(self, group_id: int):
        super().__init__("get_group_root_files", {"group_id": group_id})


class GetGroupFilesByFolderAction(Action):
    class Params(TypedDict):
        group_id: int
        folder_id: str

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("get_group_files_by_folder", kwargs)


class GetGroupFileUrlAction(Action):
    class Params(TypedDict):
        group_id: int
        file_id: str
        busid: int

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("get_group_file_url", kwargs)


class SetGroupSpecialTitleAction(Action):
    class Params(TypedDict):
        group_id: int
        user_id: int
        special_title: str

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("set_group_special_title", kwargs)


class SetGroupReactionAction(Action):
    class Params(TypedDict):
        group_id: int
        message_id: int
        code: str
        is_add: bool

    def __init__(self, **kwargs: Unpack[Params]):
        super().__init__("set_group_reaction", kwargs)


class SetEssenceMsgAction(Action):
    def __init__(self, message_id: int):
        super().__init__("set_essence_msg", {"message_id": message_id})


class GetEssenceMsgListAction(Action):
    def __init__(self, group_id):
        super().__init__("get_essence_msg_list", {"group_id": group_id})


class _GetEssenceMsgListEchoData(TypedDict):
    sender_id: int
    sender_nick: str
    sender_time: int
    operator_id: int
    operator_nick: str
    operator_time: int
    message_id: int


class _GetEssenceMsgListEchoInterface(_GetEssenceMsgListEchoData):
    content: list[Segment]


class GetEssenceMsgListEcho(Echo):
    class Model(Echo.Model):
        data: list[_GetEssenceMsgListEchoData] | None

    data: list[_GetEssenceMsgListEchoInterface] | None

    def __init__(self, **kv_pairs: Any) -> None:
        super().__init__(**kv_pairs)
        if self.data is None:
            return
        msgs: list[dict[str, Any]] = kv_pairs["data"]
        for i in range(len(msgs)):
            self.data[i]["content"] = [
                Segment.resolve(seg["type"], seg["data"]) for seg in msgs[i]["content"]
            ]


class _MFaceData(TypedDict):
    url: str
    emoji_package_id: int
    emoji_id: str
    key: str
    summary: str


class MfaceSegment(Segment[Literal["mface"], _MFaceData]):
    class Model(BaseModel):
        type: Literal["mface"]
        data: _MFaceData

    def __init__(self, **kwargs: Unpack[_MFaceData]) -> None:
        super().__init__("mface", **kwargs)

    @classmethod
    def resolve(cls, seg_type: Literal["mface"], seg_data: _MFaceData) -> Self:
        return cls(**seg_data)
