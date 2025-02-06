import json
from typing import Any

from melobot.plugin import PluginPlanner
from melobot.log import GenericLogger
from melobot.handle import on_command, GetParseArgs
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import (
    ReplySegment,
    JsonSegment,
    XmlSegment,
)
from melobot.utils.parse import CmdArgs
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent

from lemony_utils.images import text_to_imgseg
import checker_factory
import little_helper


LemonyUtils = PluginPlanner("0.1.0")
little_helper.register(
    "LemonyUtils",
    {
        "cmd": ".echo",
        "text": "复读回复的消息\n*Owner Only*",
    },
    {
        "cmd": ".{getmsg|get} [--text]",
        "text": "获取回复的消息的数据\n*Owner Only*",
    },
    {
        "cmd": ".withdraw",
        "text": "尝试撤回回复的消息\n*Owner Only*",
    },
)


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


@LemonyUtils.use
@on_command(".", " ", "echo", checker=checker_factory.get_owner_checker())
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


@LemonyUtils.use
@on_command(
    ".",
    " ",
    ["get", "getmsg"],
    checker=checker_factory.get_owner_checker(),
)
async def getmsg(
    adapter: Adapter,
    event: GroupMessageEvent,
    logger: GenericLogger,
    args: CmdArgs = GetParseArgs(),
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
    if args.vals and args.vals[0] == "--text":
        await adapter.send_reply(json.dumps(msgdata, indent=2, ensure_ascii=False))
    else:
        await adapter.send_reply(
            await text_to_imgseg(json.dumps(msgdata, indent=2, ensure_ascii=False))
        )


@LemonyUtils.use
@on_command(".", " ", "withdraw", checker=checker_factory.get_owner_checker())
async def withdraw(event: MessageEvent, adapter: Adapter):
    msg = event.get_segments(ReplySegment)
    if not msg:
        await adapter.send_reply("需要指定尝试撤回的消息")
        return
    await adapter.delete_msg(msg[0].data["id"])
