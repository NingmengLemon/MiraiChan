from melobot import Plugin
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.protocols.onebot.v11 import on_command

import checker_factory


@on_command(
    ".", " ", "withdraw", checker=lambda e: e.sender.user_id == checker_factory.owner
)
async def withdraw(event: MessageEvent, adapter: Adapter):
    msg = event.get_segments(ReplySegment)
    if not msg:
        await adapter.send_reply("需要指定尝试撤回的消息")
        return
    await adapter.delete_msg(msg[0].data["id"])


class DST(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (withdraw,)
