from collections.abc import Callable
import functools
import re
import time
from typing import Concatenate

from melobot import get_logger
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.handle import on_start_match
from sqlmodel import Session, select, col, and_, not_

from recorder_models import Message, MessageSegment
import checker_factory
from lemony_utils.images import text_to_imgseg
from .. import Recorder

plugin = PluginPlanner("0.1.0")
logger = get_logger()


def msgs_to_text(msgs: list[Message]):
    """请保持 session 开启"""
    return "\n".join(
        [
            f"[{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(msg.timestamp))}]"
            + f" {msg.sender.name}({msg.sender_id})\n"
            + "".join([s.data["text"] for s in msg.segments if s.type == "text"])
            for msg in msgs
        ]
    )


def msgs_return_text[**P, T: list[Message]](func: Callable[Concatenate[Session, P], T]):
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs):
        return msgs_to_text(func(*args, **kwargs))

    return wrapper


@msgs_return_text
def query_messages(session: Session, keyword: str, group_id: int):
    return session.exec(
        select(Message)
        .join(MessageSegment)
        .where(
            and_(
                Message.group_id == group_id,
                MessageSegment.type == "text",
                col(MessageSegment.data)["text"].icontains(keyword),
                not_(col(MessageSegment.data)["text"].startswith(".recquery")),
            )
        )
        .distinct()
        .order_by(col(Message.timestamp).asc(), col(Message.message_id).asc())
    ).all()


@plugin.use
@on_start_match(".recquery ", checker=checker_factory.get_owner_checker())
async def query(event: GroupMessageEvent, adapter: Adapter) -> None:
    words = event.text.removeprefix(".recquery ").strip()
    result = await Recorder.run_sync(
        query_messages, group_id=event.group_id, keyword=words
    )
    if not result:
        await adapter.send_reply("没有查到记录")
        return
    await adapter.send_reply(await text_to_imgseg(result))


async def get_reply(adapter: Adapter, event: GroupMessageEvent):
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


@plugin.use
@on_start_match(".getctx", checker=checker_factory.get_owner_checker())
async def get_ctx(event: GroupMessageEvent, adapter: Adapter) -> None:
    """
    usage:

    .getctx [<e>, <l>] <True/False>
    """
    base_msg = await get_reply(adapter, event)
    if not base_msg:
        return
    params = event.text.removeprefix(".getctx")
    if _ := re.search(r"\[\s*(\-?\d+)\s*\,\s*(\-?\d+)\s*\]", params, re.IGNORECASE):
        left, right = map(int, _.group(1, 2))
        params = params.replace(_.group(), "")
    else:
        left = right = 0
    _ = params.strip()
    if _.isdigit():
        sonly = bool(int(_))
    elif _.lower() == "true":
        sonly = True
    else:
        sonly = False

    result = await Recorder.run_sync(
        msgs_return_text(Recorder.get_context_messages),
        base_msgid=base_msg.data["message_id"],
        group_id=event.group_id,
        sender_id=base_msg.data["sender"].user_id,
        edge_e=left,
        edge_l=right,
        sender_only=sonly,
    )
    if not result:
        await adapter.send_reply("没有查到记录")
        return
    await adapter.send_reply(await text_to_imgseg(result))
