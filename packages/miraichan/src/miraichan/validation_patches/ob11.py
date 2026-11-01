import re
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal

from melobot.protocols.onebot.v11 import Adapter
from melobot.typ import SyncOrAsyncCallable

type _RawData = dict[str, Any]
type _PatchType = SyncOrAsyncCallable[[_RawData, Exception], None]

#: 这个补丁依赖 melobot 3.5 的 Echo.resolve 实现 (按模块全局查找 echo 类)
_SUPPORTED_MELOBOT = (3, 5)

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


def _check_melobot_version() -> None:
    try:
        raw = version("melobot")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "找不到 melobot 的安装版本, 无法确认 forward echo 补丁可用"
        ) from exc
    match = re.match(r"(\d+)\.(\d+)", raw)
    if match is None or (int(match[1]), int(match[2])) != _SUPPORTED_MELOBOT:
        supported = ".".join(map(str, _SUPPORTED_MELOBOT))
        raise RuntimeError(
            f"forward echo 补丁只支持 melobot {supported}.x, 当前是 {raw}; "
            "升级 melobot 后需要重新确认 GetForwardMsgEcho 的解析方式"
        )


def patch_forward_echo() -> None:
    """让 get_forward_msg 的回应保留原始 data.

    melobot 的 ``GetForwardMsgEcho`` 只认 ``data.message``, 而 SnowLuma 返回的是
    ``data.messages``, 构造 echo 时直接 KeyError。这里换成不解析正文的通用 echo,
    由需要正文的插件自己按两种形状读取。这是进程级补丁, 必须在任何 adapter 处理
    ``get_forward_msg`` 之前调用一次。
    """
    from melobot.protocols.onebot.v11.adapter import echo as echo_module

    _check_melobot_version()
    if getattr(echo_module.GetForwardMsgEcho, "_forward_echo_raw", False):
        return

    class _RawForwardEcho(echo_module.Echo):
        _forward_echo_raw = True

    echo_module.GetForwardMsgEcho = _RawForwardEcho  # ty: ignore[invalid-assignment]


def patch_all(adapter: Adapter) -> Adapter:
    for type_, patches in _patches.items():
        for patch in patches:
            adapter.when_validate_error(type_)(patch)
    return adapter
