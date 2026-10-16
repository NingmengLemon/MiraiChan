"""管理工具: ``.ping`` / ``.echo`` / ``.withdraw`` / ``.getmsg``。

``.ping`` 管理员可用, 其余仅 owner 可用; 没有权限时不回应。
"""

import logging
from typing import Any

from lemony_checkers import get_checker_factory_wrapper
from lemony_onebot_utils.forward import ForwardBuilder, Sender
from lemony_utils.help import Command, register_help
from melobot import PluginInfo, PluginPlanner, get_bot
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment

from .core import echo_segments, format_message_data

PLUGIN_IDENTIFIER = "toolbox"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner("1.0.0", info=PluginInfo(desc="管理工具"))
checkers = get_checker_factory_wrapper(plugin_name=PLUGIN_IDENTIFIER)

register_help(
    PLUGIN_IDENTIFIER,
    title="管理工具",
    summary="检查 bot 是否在线、复读、撤回、查看消息数据",
    aliases=["toolbox"],
    commands=[
        Command(".ping", "bot 在线时回复 pong", admin_only=True),
        Command(".echo", "回复一条消息, bot 原样再发一遍", admin_only=True),
        Command(".withdraw", "回复一条消息, 尝试撤回它", admin_only=True),
        Command(
            ".getmsg / .get",
            "回复一条消息, 以合并转发查看它的原始数据",
            admin_only=True,
        ),
    ],
)


def _reply_id(event: MessageEvent) -> int | None:
    segs = event.get_segments(ReplySegment)
    if not segs:
        return None
    try:
        return int(segs[0].data["id"])
    except (KeyError, TypeError, ValueError):
        return None


async def _get_msg_data(adapter: Adapter, message_id: int) -> dict[str, Any] | None:
    """get_msg 的原始 data (保留实现端的扩展字段); 取不到返回 None"""
    try:
        echo = (await (await adapter.get_msg(message_id)))[0]
    except Exception:
        logger.debug("get_msg %s 失败", message_id, exc_info=True)
        return None
    if echo is None or not echo.is_ok():
        return None
    data = echo.raw.get("data")
    return data if isinstance(data, dict) else None


@plugin.use
@on_command(".", " ", "ping", checker=checkers.get_admin_checker())
async def ping(adapter: Adapter) -> None:
    await adapter.send_reply("pong")


@plugin.use
@on_command(".", " ", "echo", checker=checkers.get_owner_checker())
async def echo(event: MessageEvent, adapter: Adapter) -> None:
    mid = _reply_id(event)
    if mid is None:
        await adapter.send_reply("回复一条消息来复读它")
        return
    data = await _get_msg_data(adapter, mid)
    if data is None:
        await adapter.send_reply("取不到这条消息")
        return
    segments = echo_segments(data.get("message") or [])
    if not segments:
        await adapter.send_reply("这条消息没有能复读的内容")
        return
    await adapter.send(segments)


@plugin.use
@on_command(".", " ", "withdraw", checker=checkers.get_owner_checker())
async def withdraw(event: MessageEvent, adapter: Adapter) -> None:
    mid = _reply_id(event)
    if mid is None:
        await adapter.send_reply("回复一条消息来撤回它")
        return
    try:
        result = (await (await adapter.delete_msg(mid)))[0]
    except Exception:
        logger.debug("delete_msg %s 失败", mid, exc_info=True)
        result = None
    # 撤回成功时不再出声; 失败通常是没有权限或超过了可撤回的时间
    if result is None or not result.is_ok():
        await adapter.send_reply("撤回失败")


async def _send_text_nodes(adapter: Adapter, text: str) -> None:
    """以合并转发发长文本 (超长自动拆成多个节点), 失败时退回普通消息"""
    try:
        sender = await Sender.of_bot(adapter)
        echo = await ForwardBuilder(sender).text(text).send(adapter)
    except Exception:
        logger.exception("消息数据的合并转发发送失败, 改为普通消息")
        echo = None
    if echo is None or not echo.is_ok():
        await adapter.send_reply(text)


@plugin.use
@on_command(".", " ", ["getmsg", "get"], checker=checkers.get_owner_checker())
async def getmsg(event: MessageEvent, adapter: Adapter) -> None:
    mid = _reply_id(event)
    if mid is None:
        await adapter.send_reply("回复一条消息来查看它的数据")
        return
    data = await _get_msg_data(adapter, mid)
    if data is None:
        await adapter.send_reply("取不到这条消息")
        return
    await _send_text_nodes(adapter, format_message_data(data))
