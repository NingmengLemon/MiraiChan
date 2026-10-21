"""mikufans 链接与卡片自动解析

默认行为与重构前的旧插件一致: 认出卡片里的跳转链接与正文短链, 跟随重定向, 去掉跟踪参数后回一条
干净链接。装上可选的私有 SDK 之后才有标题与播放量摘要。
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from lemony_settings import BaseSettings, require
from lemony_utils.help import register_help
from melobot import PluginPlanner, get_bot
from melobot.protocols.onebot.v11 import Adapter, MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import JsonSegment, TextSegment
from melobot.protocols.onebot.v11.handle import on_message
from pydantic import Field

from .pipeline import analyse, render
from .resolve import Brief, Resolve, make_brief, make_resolver

PLUGIN_IDENTIFIER = "mikufans"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner("0.1.0")


class MikufansSettings(BaseSettings):
    max_items: int = Field(
        default=1, ge=1, le=3, description="一条消息最多解析几个链接"
    )
    timeout: float = Field(default=10.0, gt=0, description="跟随重定向的超时 (秒)")
    rewrite_text_links: bool = Field(
        default=True, description="正文里直接出现的短链也一并净化"
    )
    enabled_groups: list[int] = Field(
        default_factory=list, description="只在这些群生效, 留空表示不限制"
    )


cfgloader = require(
    model=MikufansSettings, identifier=PLUGIN_IDENTIFIER, auto_load=False
)

register_help(
    PLUGIN_IDENTIFIER,
    title="mikufans 链接",
    summary="自动净化 mikufans 的短链与小程序卡片链接 ...以及一些妙妙功能",
    commands=[],
)


class _State:
    ready: bool = False
    resolver: Resolve | None = None
    brief: Brief | None = None


state = _State()


@plugin.on_ready
async def _() -> None:
    # melobot 会吞掉 hook 的异常, 失败只记日志
    try:
        await cfgloader.load_async()
        settings = cfgloader.value
        state.resolver = make_resolver(timeout=settings.timeout)
    except Exception:
        logger.exception("mikufans 插件初始化失败, 插件将不响应")
        return
    # 详情是可选能力, 它坏掉不能拖累链接净化
    try:
        state.brief = make_brief(timeout=max(settings.timeout, 15.0))
    except Exception:
        logger.exception("mikufans 详情初始化失败, 只做链接净化")
        state.brief = None
    if state.brief is None:
        logger.info("mikufans 详情 SDK 不在, 只做链接净化")
    state.ready = True


def _cards(event: MessageEvent) -> list[Mapping[str, Any]]:
    """取出 JSON 卡片的 payload; 解析失败的跳过"""
    payloads: list[Mapping[str, Any]] = []
    for segment in event.get_segments(JsonSegment):
        raw = segment.data.get("data")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            logger.debug("卡片 JSON 解析失败", exc_info=True)
            continue
        if isinstance(payload, Mapping):
            payloads.append(payload)
    return payloads


@plugin.use
@on_message()
async def auto_resolve(event: MessageEvent, adapter: Adapter) -> None:
    if not state.ready or state.resolver is None:
        return
    settings = cfgloader.value
    group_id = getattr(event, "group_id", None)
    if settings.enabled_groups and group_id not in settings.enabled_groups:
        return
    text = event.text or ""
    cards = _cards(event)
    if not cards and not (settings.rewrite_text_links and text):
        return
    try:
        results = await analyse(
            text if settings.rewrite_text_links else "",
            cards,
            resolve=state.resolver,
            brief=state.brief,
            max_items=settings.max_items,
        )
    except Exception:
        logger.warning("mikufans 链接解析失败", exc_info=True)
        return
    reply = render(results, plain=state.brief is None)
    if reply:
        await adapter.send_reply(TextSegment(reply))
