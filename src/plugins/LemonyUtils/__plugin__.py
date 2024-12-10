import asyncio
import json
import base64
import os
from typing import Any

from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command, on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import (
    ReplySegment,
    ImageSegment,
    JsonSegment,
    Segment,
)
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
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
    segs: list[dict[str, Any]] = []
    for i, seg in enumerate(msg.data["message"]):
        segs.append(seg.raw)
        if isinstance(seg, JsonSegment):
            segs[i]["data"]["data"] = json.loads(seg.data["data"])
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


@on_command(
    ".", " ", "withdraw", checker=lambda e: e.sender.user_id == checker_factory.owner
)
async def withdraw(event: MessageEvent, adapter: Adapter):
    msg = event.get_segments(ReplySegment)
    if not msg:
        await adapter.send_reply("需要指定尝试撤回的消息")
        return
    await adapter.delete_msg(msg[0].data["id"])


class Utils(Plugin):
    author = "LemonyNingmeng"
    version = "0.1.0"
    flows = (echo, withdraw)
