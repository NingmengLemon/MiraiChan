from typing import Any
from melobot.protocols.onebot.v11 import Adapter


async def patch_event_anonymous_missing(raw_dict: dict[str, Any], _: Exception):
    '''
    LLOneBot 4.4.3 作为实现端时，群消息的 anonymous 字段会丢失
    '''
    if raw_dict.get("message_type") == "group" and "anonymous" not in raw_dict:
        raw_dict["anonymous"] = None


def patch_all(adapter: Adapter):
    adapter.when_validate_error("event")(patch_event_anonymous_missing)
    return adapter
