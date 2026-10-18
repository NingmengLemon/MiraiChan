"""DeepSeek 的工具接口: 联网检索与网页抓取

两个接口都是普通的 POST, 用同一个 API key:

- ``POST /v1/tools/search``  ``{"query", "count", "need_content"}`` -> ``{"results": [...]}``
- ``POST /v1/tools/fetch``   ``{"url"}`` -> ``{"title", "content"}``

抓取与检索都在服务端完成, 这里只负责发请求、解析与错误归类。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx2

__all__ = ["DeepseekTools", "SearchHit", "ToolsApiError", "empty_hit"]

SEARCH_PATH = "/v1/tools/search"
FETCH_PATH = "/v1/tools/fetch"


class ToolsApiError(RuntimeError):
    """工具接口返回了非 2xx, 或者响应缺少约定字段"""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    content: str = ""


def empty_hit(url: str) -> SearchHit:
    return SearchHit(title="", url=url, content="")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


class DeepseekTools:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client

    def _ensure(self) -> httpx2.AsyncClient:
        if self._client is None:
            self._client = httpx2.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "User-Agent": "miraichan-readcheck/0.1",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure()
        try:
            response = await client.post(path, json=payload)
        except httpx2.HTTPError as exc:
            raise ToolsApiError(path, f"请求失败: {exc}") from exc
        if response.status_code >= 400:
            # 只留响应体开头, 别把整个页面塞进日志
            raise ToolsApiError(
                path, f"HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ToolsApiError(path, "响应不是 JSON") from exc
        if not isinstance(body, dict):
            raise ToolsApiError(path, "响应不是对象")
        return body

    async def search(
        self, query: str, *, count: int = 8, need_content: bool = True
    ) -> list[SearchHit]:
        body = await self._post(
            SEARCH_PATH,
            {"query": query, "count": count, "need_content": need_content},
        )
        raw = body.get("results")
        if not isinstance(raw, list):
            # 没有 results 说明响应结构变了, 不能当成"没搜到"
            raise ToolsApiError(SEARCH_PATH, f"响应里没有 results: {str(body)[:200]}")
        hits: list[SearchHit] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = _text(item.get("url"))
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=_text(item.get("title")) or url,
                    url=url,
                    content=_text(item.get("content")),
                )
            )
        return hits

    async def fetch(self, url: str) -> SearchHit:
        body = await self._post(FETCH_PATH, {"url": url})
        content = _text(body.get("content"))
        if not content:
            raise ToolsApiError(FETCH_PATH, "抓回来的正文是空的, 可能整页都是脚本渲染")
        return SearchHit(
            title=_text(body.get("title")) or url, url=url, content=content
        )
