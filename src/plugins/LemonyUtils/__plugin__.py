import json
from typing import Any

from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command, GetParseArgs
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import (
    ReplySegment,
    JsonSegment,
    XmlSegment,
)
from melobot.protocols.onebot.v11.utils import ParseArgs
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent

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
    return msg


@on_command(".", " ", "echo", checker=lambda e: e.user_id == checker_factory.owner)
async def echo(adapter: Adapter, event: MessageEvent):
    if not (msg := await get_reply(adapter, event)):
        return
    await adapter.send(
        [
            seg
            for seg in msg.data["message"]
            if not isinstance(seg, (JsonSegment, XmlSegment))
        ]
    )


@on_command(
    ".",
    " ",
    ["get", "getmsg"],
    checker=lambda e: e.user_id == checker_factory.owner,
)
async def getmsg(
    adapter: Adapter,
    event: GroupMessageEvent,
    logger: GenericLogger,
    args: ParseArgs = GetParseArgs(),
):
    if not (msg := await get_reply(adapter, event)):
        return
    msgdata: dict[str, Any] = msg.raw.get("data", {})
    msgdata.pop("raw_message", None)
    segs: list[dict[str, Any]] = []
    for i, seg in enumerate(msgdata.pop("message", [])):
        segs.append(seg.copy())
        try:
            if seg["type"] == "json":
                segs[i]["data"]["data"] = json.loads(seg["data"]["data"])
        except Exception:
            pass
    msgdata["message"] = segs

    logger.debug(f"get seg: {msg}")
    if args.vals and args.vals[0] == "text":
        await adapter.send_reply(json.dumps(msgdata, indent=2, ensure_ascii=False))
    else:
        await adapter.send_reply(
            await text_to_imgseg(json.dumps(msgdata, indent=2, ensure_ascii=False))
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
    flows = (getmsg, withdraw, echo)
