import asyncio
import json
from typing import Any

from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command, on_message, GetParseArgs
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import (
    ReplySegment,
    ImageSegment,
    JsonSegment,
    Segment,
)
from melobot.protocols.onebot.v11.utils import ParseArgs
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from pydantic import BaseModel

from lemony_utils.images import text_to_imgseg
import checker_factory


async def get_reply(adapter: Adapter, event: MessageEvent):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        await adapter.send_reply("需要指定目标消息")
        return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        await adapter.send_reply("目标消息数据获取失败")
        return
    return msg.data


@on_command(".", " ", "echo", checker=lambda e: e.user_id == checker_factory.owner)
async def echo():
    pass


@on_command(
    ".",
    " ",
    "getseg",
    checker=lambda e: e.user_id == checker_factory.owner,
)
async def getseg(
    adapter: Adapter,
    event: GroupMessageEvent,
    logger: GenericLogger,
    args: ParseArgs = GetParseArgs(),
):
    msgdata = await get_reply(adapter, event)
    segs: list[dict[str, Any]] = []
    for i, seg in enumerate(msgdata["message"]):
        segs.append(seg.raw)
        if isinstance(seg, JsonSegment):
            segs[i]["data"]["data"] = json.loads(seg.data["data"])
    logger.debug(f"get seg: {msgdata}")
    if args.vals and args.vals[0] == "text":
        await adapter.send_reply(json.dumps(segs, indent=2, ensure_ascii=False))
    else:
        await adapter.send_reply(
            await text_to_imgseg(json.dumps(segs, indent=2, ensure_ascii=False))
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
    flows = (getseg, withdraw)
