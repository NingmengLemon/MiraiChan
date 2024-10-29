from typing import Any, Type, TypedDict, Unpack, NotRequired
from melobot.protocols.onebot.v11.adapter.action import Action


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


class GetGroupRootFilesAction(Action):
    def __init__(self, group_id: int):
        super().__init__("get_group_root_files", {"group_id": group_id})


class GetGroupFilesByFolderAction(Action):
    class Params(TypedDict):
        group_id: int
        folder_id: str

    def __init__(self, kwargs: Unpack[Params]):
        super().__init__("get_group_files_by_folder", kwargs)


class GetGroupFileUrlAction(Action):
    class Params(TypedDict):
        group_id: int
        file_id: str
        busid: int

    def __init__(self, kwargs: Unpack[Params]):
        super().__init__("get_group_file_url", kwargs)


class SetGroupSpecialTitleAction(Action):
    class Params(TypedDict):
        group_id: int
        user_id: int
        special_title: str

    def __init__(self, kwargs: Unpack[Params]):
        super().__init__("set_group_special_title", kwargs)


class SetGroupReactionAction(Action):
    class Params(TypedDict):
        group_id: int
        message_id: int
        code: str
        is_add: bool

    def __init__(self, kwargs: Unpack[Params]):
        super().__init__("set_group_reaction", kwargs)
