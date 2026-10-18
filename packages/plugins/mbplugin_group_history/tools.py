"""给模型用的只读工具: 检索群史、统计发言、看某人说过什么"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from lemony_llm_provider import ToolSpec
from sqlalchemy.ext.asyncio import AsyncSession

from .history import (
    GroupRef,
    find_conversation_id,
    search_messages,
    speaker_stats,
)

__all__ = ["TOOL_SPECS", "HistoryTools", "ToolContext"]

SessionFactory = Callable[[], Any]  # 返回 AsyncSession 的异步上下文管理器

_WS = re.compile(r"\s+")


def _clip(text: str, limit: int) -> str:
    text = _WS.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_hit(index: int, sent_at: datetime, sender: str, text: str) -> str:
    return f"{index}. [{sent_at:%m-%d %H:%M}] {_clip(sender, 24)}: {_clip(text, 160)}"


@dataclass(frozen=True, slots=True)
class ToolContext:
    ref: GroupRef
    now: datetime
    window_days: int
    max_window_days: int
    result_limit: int
    max_tool_chars: int


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="search_history",
        description=(
            "在群聊记录里按关键词检索消息。多个关键词之间是「同时包含」; "
            "也可以用 speaker 限定只找某个人说的。返回最近的若干条。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关键词, 可以为空, 表示不按词过滤",
                },
                "speaker": {
                    "type": "string",
                    "description": "只找这个发言者(群名片或昵称的一部分)",
                },
                "days": {
                    "type": "integer",
                    "description": "往回查多少天, 不传就用默认窗口",
                },
                "limit": {"type": "integer", "description": "最多返回多少条"},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="speaker_stats",
        description="统计一段时间内群里谁发言最多, 用来判断谁对这个话题最活跃。",
        parameters={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "往回统计多少天"},
                "limit": {"type": "integer", "description": "最多列几个人"},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="speaker_messages",
        description="看某个群友最近说过的话, 用来画人物画像或者确认他的口头禅。",
        parameters={
            "type": "object",
            "properties": {
                "speaker": {
                    "type": "string",
                    "description": "发言者(群名片或昵称的一部分)",
                },
                "days": {"type": "integer", "description": "往回查多少天"},
                "limit": {"type": "integer", "description": "最多返回多少条"},
            },
            "required": ["speaker"],
            "additionalProperties": False,
        },
    ),
)


class HistoryTools:
    """把工具调用翻成对 recorder 库的只读查询"""

    def __init__(self, session_factory: SessionFactory, context: ToolContext) -> None:
        self._session_factory = session_factory
        self._context = context
        self._conversation_id: UUID | None = None
        self._resolved = False

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return TOOL_SPECS

    async def _conversation(self, session: AsyncSession) -> UUID | None:
        if not self._resolved:
            self._conversation_id = await find_conversation_id(
                session, self._context.ref
            )
            self._resolved = True
        return self._conversation_id

    def _window(self, days: Any) -> datetime:
        context = self._context
        requested = days if isinstance(days, int) and days > 0 else context.window_days
        return context.now - timedelta(days=min(requested, context.max_window_days))

    def _limit(self, value: Any) -> int:
        if isinstance(value, int) and value > 0:
            return min(value, self._context.result_limit)
        return self._context.result_limit

    async def call(self, name: str, arguments: Mapping[str, Any]) -> str:
        try:
            if name == "search_history":
                return await self._search(arguments)
            if name == "speaker_stats":
                return await self._stats(arguments)
            if name == "speaker_messages":
                return await self._speaker(arguments)
        except Exception as exc:  # noqa: BLE001 - 工具错误要回给模型而不是炸掉整轮
            return f"工具 {name} 出错: {exc}"
        return f"没有名为 {name} 的工具"

    async def _search(self, arguments: Mapping[str, Any]) -> str:
        context = self._context
        raw_keywords = arguments.get("keywords") or ()
        keywords = tuple(
            str(item).strip() for item in raw_keywords if str(item).strip()
        )
        speaker = _optional_str(arguments.get("speaker"))
        since = self._window(arguments.get("days"))
        limit = self._limit(arguments.get("limit"))
        if not keywords and not speaker:
            return "至少给一个关键词或一个发言者, 否则只能全量倒序, 没有意义"
        async with self._session_factory() as session:
            conversation_id = await self._conversation(session)
            if conversation_id is None:
                return "没有找到这个群的记录, 可能是记录器还没写入过这个群"
            hits = await search_messages(
                session,
                conversation_id,
                since=since,
                keywords=keywords,
                speaker=speaker,
                exclude_sender_external_ids=(context.ref.self_id,),
                limit=limit,
            )
        if not hits:
            return f"从 {since:%Y-%m-%d} 到现在没有匹配的消息"
        lines = [
            _format_hit(index, hit.sent_at, hit.sender, hit.text)
            for index, hit in enumerate(hits, start=1)
        ]
        return _clip("\n".join(lines), context.max_tool_chars)

    async def _stats(self, arguments: Mapping[str, Any]) -> str:
        context = self._context
        since = self._window(arguments.get("days"))
        limit = self._limit(arguments.get("limit"))
        async with self._session_factory() as session:
            conversation_id = await self._conversation(session)
            if conversation_id is None:
                return "没有找到这个群的记录, 可能是记录器还没写入过这个群"
            stats = await speaker_stats(
                session,
                conversation_id,
                since=since,
                exclude_sender_external_ids=(context.ref.self_id,),
                limit=limit,
            )
        if not stats:
            return f"从 {since:%Y-%m-%d} 到现在没有可统计的消息"
        total = sum(item.count for item in stats)
        lines = [
            f"{index}. {_clip(item.sender, 24)}: {item.count} 条"
            for index, item in enumerate(stats, start=1)
        ]
        header = f"从 {since:%Y-%m-%d} 起共 {total} 条(只统计前 {len(stats)} 名):"
        return _clip("\n".join([header, *lines]), context.max_tool_chars)

    async def _speaker(self, arguments: Mapping[str, Any]) -> str:
        context = self._context
        speaker = _optional_str(arguments.get("speaker"))
        if not speaker:
            return "需要给出要查的发言者"
        since = self._window(arguments.get("days"))
        limit = self._limit(arguments.get("limit"))
        async with self._session_factory() as session:
            conversation_id = await self._conversation(session)
            if conversation_id is None:
                return "没有找到这个群的记录, 可能是记录器还没写入过这个群"
            hits = await search_messages(
                session,
                conversation_id,
                since=since,
                speaker=speaker,
                exclude_sender_external_ids=(context.ref.self_id,),
                limit=limit,
            )
        if not hits:
            return f"从 {since:%Y-%m-%d} 到现在没有找到 {speaker} 的发言"
        lines = [
            _format_hit(index, hit.sent_at, hit.sender, hit.text)
            for index, hit in enumerate(hits, start=1)
        ]
        return _clip("\n".join(lines), context.max_tool_chars)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
