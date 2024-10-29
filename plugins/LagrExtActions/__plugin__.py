from melobot import Plugin

from .actions import (
    FetchCustomFaceAction,
    FriendPokeAction,
    GetFriendMsgHistoryAction,
    GetGroupFileUrlAction,
    GetGroupFilesByFolderAction,
    GetGroupMsgHistoryAction,
    GetGroupRootFilesAction,
    GroupPokeAction,
    SetGroupReactionAction,
    SetGroupSpecialTitleAction,
    UploadGroupFileAction,
    UploadPrivateFileAction,
)


class LagrExtAPI(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    funcs = (
        FriendPokeAction,
        GroupPokeAction,
        FetchCustomFaceAction,
        GetFriendMsgHistoryAction,
        GetGroupMsgHistoryAction,
        UploadGroupFileAction,
        UploadPrivateFileAction,
        GetGroupRootFilesAction,
        GetGroupFilesByFolderAction,
        GetGroupFileUrlAction,
        SetGroupSpecialTitleAction,
        SetGroupReactionAction,
    )
