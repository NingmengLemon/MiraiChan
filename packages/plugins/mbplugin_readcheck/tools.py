"""给模型用的工具: 联网检索与抓取正文"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from lemony_llm_provider import ToolSpec

from .webapi import DeepseekTools, SearchHit, ToolsApiError

__all__ = ["TOOL_SPECS", "WebTools", "build_read_question", "is_http_url"]

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="web_search",
        description=(
            "联网检索。返回标题、链接与摘要, 强时效的问题(价格、版本、排名、日程)务必用它取证。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词, 越具体越好"},
                "count": {
                    "type": "integer",
                    "description": "返回多少条, 默认 8",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="fetch_page",
        description="抓取一个网页的正文, 用于读全文或确认搜索摘要里看不到的细节。",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "http(s) 链接"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    ),
)


def is_http_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


def _clip(text: str, limit: int) -> str:
    collapsed = _WS.sub(" ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


class WebTools:
    def __init__(
        self,
        api: DeepseekTools,
        *,
        search_count: int = 8,
        max_result_chars: int = 700,
        max_fetch_chars: int = 12000,
    ) -> None:
        self._api = api
        self._search_count = search_count
        self._max_result_chars = max_result_chars
        self._max_fetch_chars = max_fetch_chars

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return TOOL_SPECS

    async def call(self, name: str, arguments: Mapping[str, Any]) -> str:
        try:
            if name == "web_search":
                return await self._search(arguments)
            if name == "fetch_page":
                return await self._fetch(arguments)
        except ToolsApiError as exc:
            logger.warning("联网工具失败 [%s]: %s", name, exc)
            return f"{name} 调用失败: {exc}。可以换个关键词, 或者直接说明无法核实。"
        return f"没有名为 {name} 的工具"

    async def _search(self, arguments: Mapping[str, Any]) -> str:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return "需要给出检索词"
        raw_count = arguments.get("count")
        count = (
            min(int(raw_count), 20)
            if isinstance(raw_count, int) and raw_count > 0
            else self._search_count
        )
        hits = await self._api.search(query, count=count)
        if not hits:
            return f"没有搜到与 {query!r} 相关的结果"
        lines: list[str] = []
        for index, hit in enumerate(hits, start=1):
            lines.append(self._format_hit(index, hit))
        return "\n".join(lines)

    def _format_hit(self, index: int, hit: SearchHit) -> str:
        head = f"{index}. {_clip(hit.title, 80)}\n   {hit.url}"
        if hit.content:
            return f"{head}\n   {_clip(hit.content, self._max_result_chars)}"
        return head

    async def _fetch(self, arguments: Mapping[str, Any]) -> str:
        url = str(arguments.get("url") or "").strip()
        if not is_http_url(url):
            return "只支持 http(s) 链接"
        page = await self._api.fetch(url)
        body = _clip(page.content, self._max_fetch_chars)
        return f"{page.title}\n{url}\n\n{body}"


def build_read_question(argument: str, article: str, limit: int) -> str:
    """把用户给的东西拼成精读的提问: 有正文就直接带, 只有链接就让它自己抓"""
    if article:
        return f"请精读这篇文章: {argument}\n\n{article[:limit]}"
    if is_http_url(argument):
        # 预抓取失败时让模型自己调 fetch_page
        return f"请精读这个链接, 先用 fetch_page 取正文: {argument}"
    return f"请精读下面这段文字:\n\n{argument[:limit]}"
