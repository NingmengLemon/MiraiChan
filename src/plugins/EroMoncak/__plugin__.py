import functools
from typing import Sequence

from melobot import Plugin, send_text, get_logger
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.protocols.onebot.v11 import on_message
import pypinyin

from configloader import ConfigLoader, ConfigLoaderMetadata
from .. import AliasProvider


logger = get_logger()

get_pinyin = functools.partial(pypinyin.lazy_pinyin, style=pypinyin.Style.TONE3)


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
        if (
            sender.user_id
            and (alias := await AliasProvider.get_alias(sender.user_id)) is not None
        ):
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
        and await AliasProvider.if_alias_exists((alias := text[1:].strip()))
    ):
        await send_text(f"涩{alias}")


class EroMoncak(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (say_noero, repeat_ero)
