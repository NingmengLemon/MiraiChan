import asyncio
from collections.abc import Callable
import functools
import re
import traceback
from typing import Concatenate

from melobot import send_text
from melobot.adapter.generic import _get_ctx_adapter
from melobot.log import GenericLogger
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, TextSegment
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.handle import on_command
from melobot.ctx import EventOrigin
from melobot.utils.parse import CmdArgs
from melobot.utils import unfold_ctx
from melobot.session import Rule, enter_session, suspend
from sqlmodel import Session

import checker_factory
from recorder_models import Message
from lemony_utils.botutils import get_reply
from lemony_utils.images import SelfHostSource, default_font_cache, text_to_imgseg

from .core import (
    QuoteFactory,
    prepare_quote,
    gather_resources,
)
from .. import Recorder

# TODO: 增加配置文件
reply_relation_cache: dict[int, int] = {}
quote_factory = QuoteFactory(
    font=default_font_cache, emoji_source=SelfHostSource("http://172.16.40.4:10712/")
)


async def get_reply_id(adapter: Adapter, event: MessageEvent) -> int:
    if event.message_id in reply_relation_cache:
        return reply_relation_cache[event.message_id]
    echo = await get_reply(adapter, event)
    reply_relation_cache[event.message_id] = echo.data["message_id"]
    return echo.data["message_id"]


same_msg_min_dist = 60 * 30  # 同一条消息被再次引用时需要和上次引用的最小间隔
plugin = PluginPlanner("0.1.0")


class SameReplyRule(Rule[GroupMessageEvent]):
    async def compare(self, e1, e2):
        adapter = EventOrigin.get_origin(e1).adapter
        if not isinstance(adapter, Adapter):
            return False
        try:
            r1, r2 = await get_reply_id(adapter, e1), await get_reply_id(adapter, e2)
        except get_reply.GetReplyException:
            return False
        return r1 == r2


rule = SameReplyRule()


def just_prepare_quote_data_decorator[
    **P
](func: Callable[Concatenate[Session, P], list[Message]]):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return prepare_quote(func(*args, **kwargs))

    return wrapper


just_prepare = just_prepare_quote_data_decorator(Recorder.get_context_messages)


def auto_report_traceback(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            adapter = _get_ctx_adapter()
            if isinstance(adapter, Adapter):
                await adapter.send(
                    [
                        TextSegment("出现了错误: \n"),
                        await text_to_imgseg(traceback.format_exc()),
                    ]
                )
            else:
                await send_text("出现了错误: \n" + traceback.format_exc())
            raise

    return wrapper


@plugin.use
@on_command(
    ".",
    " ",
    ["mq", "momoquote"],
    decos=[
        auto_report_traceback,
        unfold_ctx(
            lambda: enter_session(
                rule, wait=False, nowait_cb=lambda: send_text("MomoQuote 正忙, 请稍等")
            )
        ),
    ],
    checker=checker_factory.get_owner_checker(),
)
async def quote(
    adapter: Adapter,
    event: GroupMessageEvent,
    logger: GenericLogger,
):
    if not Recorder.ready_event.is_set():
        await adapter.send_reply("数据库还未就绪")
        return
    try:
        target = await get_reply(adapter, event)
    except get_reply.GetReplyException:
        await adapter.send_reply("获取目标消息失败")
        return

    params = event.text.split(" ", maxsplit=1)[-1]
    if _ := re.search(r"\[\s*(\-?\d+)\s*\,\s*(\-?\d+)\s*\]", params, re.IGNORECASE):
        left, right = map(int, _.group(1, 2))
        params = params.replace(_.group(), "")
    else:
        left = right = 0
    _ = params.strip()
    if _.isdigit():
        sender_only = bool(int(_))
    elif _.lower() in ("true", "1", "yes"):
        sender_only = True
    else:
        sender_only = False
    await adapter.send("已开始生成图像, 请稍等")
    logger.debug(
        f"Preparing quote of {target.data}, [{left}, {right}], sender_only={sender_only}"
    )
    data, resources = await Recorder.run_sync(
        just_prepare,
        base_msgid=target.data["message_id"],
        group_id=event.group_id,
        sender_id=target.data["sender"].user_id,
        edge_e=left,
        edge_l=right,
        sender_only=sender_only,
    )
    # TODO: 增加空信息判定
    # TODO: 增加参数选项
    logger.debug(f"Got QuoteData: {data!r}")
    # TODO: 增加已保存的本地资源的引用
    resources = await gather_resources(resources)
    logger.debug(f"Got {len(resources)} resources")
    result = await asyncio.to_thread(quote_factory.quote_sync, data, resources)
    await adapter.send(ImageSegment(file=result))
    # TODO: 增加保存到本地

    while True:
        if not await suspend(same_msg_min_dist):
            return
        await adapter.send_reply("引用此消息过于频繁, 请稍候再试")
        # TODO: 将频繁引用检查智能化 (因为现在是区间引用, 考虑把区间参数加到 rule 里?)
