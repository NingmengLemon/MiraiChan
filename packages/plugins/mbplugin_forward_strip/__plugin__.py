"""转发消息缩水: 回复一条合并转发, ``.strip [a:b]`` 截掉多余的部分再发回来

昵称与头像靠原样回填每个节点的 uin/name, 不做任何伪造。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from lemony_settings import BaseSettings, require
from lemony_utils.help import Command, register_help
from melobot import PluginPlanner, get_bot
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, TextSegment
from pydantic import Field

from .pipeline import StripError, strip_forward

PLUGIN_IDENTIFIER = "forward_strip"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner("0.1.0")


class StripSettings(BaseSettings):
    max_nodes: int = 100
    enabled_groups: list[int] = Field(default_factory=list)


cfgloader = require(model=StripSettings, identifier=PLUGIN_IDENTIFIER, auto_load=False)

register_help(
    PLUGIN_IDENTIFIER,
    title="转发缩水",
    summary="把合并转发末尾的广告截掉, 昵称与头像保持原样",
    commands=[Command(".strip [a:b]", "回复一条合并转发, 按 Python 切片保留节点")],
)


class _AdapterIo:
    """ForwardIo 的 melobot 实现"""

    def __init__(self, adapter: Adapter, *, self_id: int) -> None:
        self._adapter = adapter
        self._self_id = self_id

    async def get_message_segments(self, message_id: int) -> list[Any]:
        group = await self._adapter.get_msg(message_id)
        try:
            echo = await group.unwrap(0)
        except Exception as exc:
            raise StripError("取不到这条消息") from exc
        if echo.data is None:
            raise StripError("取不到这条消息")
        return list(echo.data["message"])

    async def get_forward_nodes(self, forward_id: str) -> list[Any]:
        group = await self._adapter.get_forward_msg(forward_id)
        try:
            echo = await group.unwrap(0)
        except Exception as exc:
            raise StripError("取不到转发内容") from exc
        if echo.data is None:
            raise StripError("取不到转发内容")
        return list(echo.data["message"])

    async def send_forward_nodes(
        self, group_id: int, nodes: Sequence[dict[str, Any]]
    ) -> None:
        group = await self._adapter.send_forward_custom(nodes, group_id=group_id)
        try:
            await group.unwrap(0)
        except Exception as exc:
            raise StripError("转发没有发出去") from exc


@dataclass
class _State:
    ready: bool = False


state = _State()


@plugin.on_ready
async def _() -> None:
    # melobot 会吞掉 hook 的异常, 失败只记日志
    try:
        await cfgloader.load_async()
        state.ready = True
    except Exception:
        logger.exception("forward_strip 初始化失败, 插件将不响应")


def _argument_of(event: GroupMessageEvent) -> str:
    text = (event.text or "").strip()
    return re.sub(r"^[.。]\s*(?:strip|剪)\s*", "", text, count=1, flags=re.I).strip()


def _reply_id(event: GroupMessageEvent) -> int | None:
    replies = event.get_segments(ReplySegment)
    if not replies:
        return None
    try:
        return int(replies[0].data["id"])
    except (KeyError, TypeError, ValueError):
        return None


@plugin.use
@on_command(".", " ", ["strip", "剪"])
async def strip_command(event: GroupMessageEvent, adapter: Adapter) -> None:
    if not state.ready:
        await adapter.send_reply(TextSegment("转发缩水还没准备好"))
        return
    settings = cfgloader.value
    if settings.enabled_groups and event.group_id not in settings.enabled_groups:
        await adapter.send_reply(TextSegment("这个群没有开启转发缩水"))
        return
    spec = _argument_of(event)
    if not spec:
        await adapter.send_reply(
            TextSegment("用法: 回复一条合并转发, 发 .strip [:-3] 这样的切片")
        )
        return
    reply_id = _reply_id(event)
    if reply_id is None:
        await adapter.send_reply(TextSegment("要先回复一条合并转发"))
        return
    io = _AdapterIo(adapter, self_id=event.self_id)
    try:
        result = await strip_forward(
            io,
            group_id=event.group_id,
            reply_message_id=reply_id,
            spec=spec,
            max_nodes=settings.max_nodes,
        )
    except StripError as exc:
        await adapter.send_reply(TextSegment(str(exc)))
        return
    except Exception:
        logger.exception(
            "转发缩水失败: group=%s reply=%s spec=%s", event.group_id, reply_id, spec
        )
        await adapter.send_reply(TextSegment("处理失败了"))
        return
    note = f"已保留 {result.kept}/{result.total} 条"
    if result.nested and result.dropped_nested:
        note += ", 嵌套转发已省略"
    logger.info(
        "转发缩水完成: group=%s 保留 %s/%s 嵌套 %s",
        event.group_id,
        result.kept,
        result.total,
        result.nested,
    )
    await adapter.send_reply(TextSegment(note))
