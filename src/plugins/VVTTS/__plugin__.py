import re
from melobot.plugin import PluginPlanner
from melobot.log import GenericLogger
from melobot.handle import on_start_match, on_command
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import RecordSegment
from melobot.utils.parse import CmdArgs
from melobot.utils import lock

import romajitable

from .client import VoicevoxEngineClient
from lemony_utils.images import bytes_to_b64_url
from lemony_utils.pinyin import pinyin_to_katakana

vvtts = PluginPlanner("0.1.0")


def is_jpn(text):
    chinese_count = 0
    japanese_count = 0
    other_count = 0

    for char in text:
        # 汉字
        if "\u4e00" <= char <= "\u9fff":
            chinese_count += 1
        # 平假名
        elif "\u3040" <= char <= "\u309f":
            japanese_count += 1
        # 片假名
        elif "\u30a0" <= char <= "\u30ff":
            japanese_count += 1
        else:
            other_count += 1

    if japanese_count * 2 > chinese_count / 2:
        return True
    return False


def en2ktkn(m: re.Match) -> str:
    return romajitable.to_kana(m.group(0)).katakana


@vvtts.use
@on_start_match(".tts ")
@lock()
async def do_tts(event: MessageEvent, adapter: Adapter, logger: GenericLogger):
    text = event.text.strip().removeprefix(".tts").strip()
    if len(text) > 250:
        await adapter.send_reply("消息过长")
        return
    elif len(text) == 0:
        await adapter.send_reply("消息是空的")
        return
    logger.debug(f"original text: {text!r}")
    if not is_jpn(text):
        text = "".join(pinyin_to_katakana(text))
    text = re.sub(r"(?=[a-z]*[aeiou])[a-z]{2,}", en2ktkn, text, flags=re.IGNORECASE)
    logger.debug(f"final text to tts: {text!r}")

    async with VoicevoxEngineClient() as session:
        accent_data = await session.audio_query(text, 1)
        if not accent_data["kana"]:
            await adapter.send_reply("不是有效的消息")
            return
        logger.debug(f"kana from vv: {accent_data["kana"]!r}")
        audiobytes = await session.synthesis(accent_data, 1)
    audiob64url = bytes_to_b64_url(audiobytes)
    await adapter.send(RecordSegment(file=audiob64url))


# args support
@on_command(".", " ", "speak")
async def speak_msg(
    event: MessageEvent,
    adapter: Adapter,
    logger: GenericLogger,
    args: CmdArgs,
):
    raise NotImplementedError()
