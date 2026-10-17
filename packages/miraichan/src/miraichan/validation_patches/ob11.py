from collections.abc import Callable
from typing import Any, Literal

from melobot.protocols.onebot.v11 import Adapter
from melobot.typ import SyncOrAsyncCallable

type _RawData = dict[str, Any]
type _PatchType = SyncOrAsyncCallable[[_RawData, Exception], None]

_patches: dict[Literal["echo", "event"], list[_PatchType]] = {
    "echo": [],
    "event": [],
}


def mark_patch(type_: Literal["echo", "event"]) -> Callable[[_PatchType], _PatchType]:
    def deco(func: _PatchType) -> _PatchType:
        _patches[type_].append(func)
        return func

    return deco


@mark_patch("event")
async def patch_event_anonymous_missing(raw_dict: _RawData, _: Exception) -> None:
    """
    LLOneBot 4.4.3 作为实现端时，群消息的 anonymous 字段不存在
    """
    if raw_dict.get("message_type") == "group" and "anonymous" not in raw_dict:
        raw_dict["anonymous"] = None


@mark_patch("echo")
async def patch_echo_data_missing(raw_dict: _RawData, _: Exception) -> None:
    """
    LLOneBot 4.4.3 作为实现端时，delete_msg 的 echo 的 data 字段不存在
    """
    if "data" not in raw_dict:
        raw_dict["data"] = None


@mark_patch("echo")
async def patch_echo_get_group_member_list_none(
    raw_dict: _RawData, _: Exception
) -> None:
    """
    Lagrange.OneBot 作为实现端时，get_group_member_list 的 echo 的 成员信息中的 card 字段可能为 None

    把别的字段也顺便检查了
    """
    if raw_dict.get("action_type") == "get_group_member_list":
        for i in raw_dict["data"]:
            for k, v in list(i.items()):
                if v is None:
                    i[k] = ""


@mark_patch("event")
async def patch_event_private_empty_record_segment(
    raw_dict: _RawData, _: Exception
) -> None:
    """
    Lagrange.OneBot 作为实现端时，私聊的单个语音消息中可能有多个 RecordSegment，且只有其中一个有内容

    这会导致 melobot 报一个 KeyError，不知道为什么
    """
    if raw_dict.get("message_type") == "private":
        raw_dict["message"] = [
            seg
            for seg in raw_dict["message"]
            if (
                seg["type"] != "record"
                or (
                    seg["type"] == "record"
                    and seg["data"]["file"]
                    and seg["data"]["url"]
                )
            )
        ]


def patch_all(adapter: Adapter) -> Adapter:
    for type_, patches in _patches.items():
        for patch in patches:
            adapter.when_validate_error(type_)(patch)
    return adapter
