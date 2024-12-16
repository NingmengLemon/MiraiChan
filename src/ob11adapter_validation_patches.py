from typing import Any
from melobot.protocols.onebot.v11 import Adapter

_RawData = dict[str, Any]


async def patch_event_anonymous_missing(raw_dict: _RawData, _: Exception):
    """
    LLOneBot 4.4.3 作为实现端时，群消息的 anonymous 字段不存在
    """
    if raw_dict.get("message_type") == "group" and "anonymous" not in raw_dict:
        raw_dict["anonymous"] = None


async def patch_echo_data_missing(raw_dict: _RawData, _: Exception):
    """
    LLOneBot 4.4.3 作为实现端时，delete_msg 的 echo 的 data 字段不存在
    """
    if "data" not in raw_dict:
        raw_dict["data"] = None


def patch_all(adapter: Adapter):
    adapter.when_validate_error("event")(patch_event_anonymous_missing)
    adapter.when_validate_error("echo")(patch_echo_data_missing)
    return adapter
