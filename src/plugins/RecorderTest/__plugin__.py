import time

from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.handle import on_start_match
from sqlmodel import select, col, func, and_

from recorder_models import User, Group, Message, MessageSegment, Image
import checker_factory
from .. import Recorder

plugin = PluginPlanner("0.1.0")


@plugin.use
@on_start_match(".recquery ", checker=lambda e: e.user_id == checker_factory.OWNER)
async def query(event: GroupMessageEvent, adapter: Adapter) -> None:
    words = event.text.removeprefix(".recquery ").strip()
    with Recorder.get_session() as session:
        msgs = session.exec(
            select(Message)
            .join(MessageSegment)
            .where(
                and_(
                    Message.group_id == event.group_id,
                    MessageSegment.type == "text",
                    col(MessageSegment.data)["text"].icontains(words),
                )
            )
            .distinct()
            .order_by(col(Message.timestamp).desc())
        ).all()
        if not msgs:
            await adapter.send_reply("没有查到记录")
            return
        await adapter.send_reply(
            "\n".join(
                [
                    f"[{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(msg.timestamp))}]"
                    + f" {msg.sender.name}({msg.sender_id})\n"
                    + "".join(
                        [s.data["text"] for s in msg.segments if s.type == "text"]
                    )
                    for msg in msgs
                ]
            )
        )
