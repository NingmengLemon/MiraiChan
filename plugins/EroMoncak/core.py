import atexit
import functools
import hashlib
import re
from typing import Sequence
from melobot import Plugin, send_text, get_bot, get_logger
from melobot.handle import stop, bypass
from melobot.protocols.onebot.v11.adapter.event import MessageEvent, MetaEvent
from melobot.protocols.onebot.v11.adapter.segment import (
    AtSegment,
    TextSegment,
    ReplySegment,
)
from melobot.protocols.onebot.v11 import (
    on_command,
    on_meta,
    on_message,
    on_start_match,
    ParseArgs,
    Adapter,
)
from melobot.protocols.onebot.v11.handle import GetParseArgs
from melobot.protocols.onebot.v11.utils import CmdArgFormatter
from pydantic import BaseModel
import pypinyin

from configloader import ConfigLoader, ConfigLoaderMetadata


class EroMoncakConfigDef(BaseModel):
    user_alias: dict[int, str] = {}


logger = get_logger()
bot = get_bot()
user_alias: dict[int, str] = bot.get_share("AliasProvider", "user_alias").get()

get_pinyin = functools.partial(pypinyin.lazy_pinyin, style=pypinyin.Style.TONE3)
logger.info("EroMoncak is ready for love")


def is_hans(letter: str):
    return 0x4E00 < ord(letter) < 0x9FA5


def match_pinyin(hanss: str, pins: Sequence[str]):
    hanssf = list(filter(is_hans, hanss))
    if len(hanssf) != len(pins):
        return False
    return get_pinyin(hanssf) == (pins if isinstance(pins, list) else list(pins))


@on_message()
async def say_noero(event: MessageEvent):
    text = event.text.strip()
    if match_pinyin(text, ["hao3", "se4"]):
        sender = event.sender
        if sender.user_id and (alias := user_alias.get(sender.user_id)):
            await send_text(f"涩{alias}")
        else:
            await send_text("不许涩涩")


@on_message()
async def repeat_ero(event: MessageEvent):
    text = event.text.strip()
    if (
        len(text) > 1
        and is_hans(text[0])
        and get_pinyin(text[0])[0] == "se4"
        and (alias := text[1:].strip()) in user_alias.values()
    ):
        await send_text(f"涩{alias}")


class EroMoncak(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (say_noero, repeat_ero)
