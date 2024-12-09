import asyncio
import json
import base64
import os

from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command, on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from pydantic import BaseModel

from lemony_utils.images import text_to_image, to_b64_url
import checker_factory


@on_command(
    ".",
    " ",
    "echo",
    checker=lambda e: e.user_id == checker_factory.owner,
)
async def echo(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        await adapter.send_reply("需要指定目标消息")
        return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        await adapter.send_reply("目标消息数据获取失败")
        return
    segs = [seg.raw for seg in msg.data["message"]]
    logger.debug(f"echoing: {msg}, {segs=}")
    await adapter.send_reply(
        ImageSegment(
            file=await asyncio.to_thread(
                lambda: to_b64_url(
                    text_to_image(json.dumps(segs, indent=2, ensure_ascii=False))
                )
            )
        )
    )


class Utils(Plugin):
    author = "LemonyNingmeng"
    version = "0.1.0"
    flows = (echo,)
