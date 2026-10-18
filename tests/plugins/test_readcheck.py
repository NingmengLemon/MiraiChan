"""精读与核查: 联网客户端、工具层与提问拼装

网络部分用 httpx2 的 MockTransport 打桩, 不打真实接口。
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from mbplugin_readcheck.tools import WebTools, build_read_question, is_http_url
from mbplugin_readcheck.webapi import DeepseekTools, ToolsApiError

pytestmark = pytest.mark.asyncio

BASE = "https://api.deepseek.com"


def _client(handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=BASE,
        transport=httpx2.MockTransport(handler),
        headers={"Authorization": "Bearer test"},
    )


async def _search_handler(request: httpx2.Request) -> httpx2.Response:
    assert request.url.path == "/v1/tools/search"
    payload = json.loads(request.content)
    assert payload["query"] == "glm 5.3 flash"
    assert payload["need_content"] is True
    return httpx2.Response(
        200,
        json={
            "results": [
                {
                    "title": "GLM 5.3 Flash 发布",
                    "url": "https://a.example/x",
                    "content": "摘要一",
                },
                {"url": "https://b.example/y"},
                {"title": "没有链接的条目"},
            ]
        },
    )


@pytest_asyncio.fixture
async def api() -> AsyncIterator[DeepseekTools]:
    client = _client(_search_handler)
    try:
        yield DeepseekTools(BASE, "test", client=client)
    finally:
        await client.aclose()


async def test_search_parses_and_skips_broken_rows(api: DeepseekTools) -> None:
    hits = await api.search("glm 5.3 flash", count=8)
    assert [hit.url for hit in hits] == ["https://a.example/x", "https://b.example/y"]
    assert hits[0].title == "GLM 5.3 Flash 发布"
    # 没有标题时用链接顶上, 免得模型看到空行
    assert hits[1].title == "https://b.example/y"


async def test_search_without_results_is_an_error() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": []})

    client = _client(handler)
    try:
        with pytest.raises(ToolsApiError, match="results"):
            await DeepseekTools(BASE, "t", client=client).search("x")
    finally:
        await client.aclose()


async def test_http_error_is_reported_without_the_key() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, text='{"error":"bad key"}')

    client = _client(handler)
    try:
        with pytest.raises(ToolsApiError) as info:
            await DeepseekTools(BASE, "secret-value", client=client).search("x")
        assert "401" in str(info.value)
        assert "secret-value" not in str(info.value)
    finally:
        await client.aclose()


async def test_empty_fetch_body_is_an_error() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/tools/fetch"
        return httpx2.Response(200, json={"title": "空页", "content": "   "})

    client = _client(handler)
    try:
        with pytest.raises(ToolsApiError, match="正文是空的"):
            await DeepseekTools(BASE, "t", client=client).fetch("https://a.example")
    finally:
        await client.aclose()


class _FakeApi(DeepseekTools):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(BASE, "t", client=_client(_search_handler))
        self._fail = fail

    async def search(self, query: str, *, count: int = 8, need_content: bool = True):  # type: ignore[override]
        from mbplugin_readcheck.webapi import SearchHit

        if self._fail:
            raise ToolsApiError("/v1/tools/search", "HTTP 500")
        return [
            SearchHit(title="t" * 200, url="https://a.example/x", content="c" * 2000)
        ]

    async def fetch(self, url: str):  # type: ignore[override]
        from mbplugin_readcheck.webapi import SearchHit

        return SearchHit(title="标题", url=url, content="正文" * 3000)


async def test_tool_output_is_clipped() -> None:
    tools = WebTools(_FakeApi(), max_result_chars=100, max_fetch_chars=50)
    text = await tools.call("web_search", {"query": "x"})
    assert "https://a.example/x" in text
    assert len(text) < 400
    page = await tools.call("fetch_page", {"url": "https://a.example/x"})
    assert page.startswith("标题")
    assert len(page) < 200


async def test_tool_guards() -> None:
    tools = WebTools(_FakeApi())
    assert "需要给出检索词" in await tools.call("web_search", {})
    assert "只支持 http(s)" in await tools.call("fetch_page", {"url": "file:///etc"})
    assert "没有名为" in await tools.call("nope", {})


async def test_tool_failure_is_reported_to_the_model() -> None:
    tools = WebTools(_FakeApi(fail=True))
    text = await tools.call("web_search", {"query": "x"})
    assert "调用失败" in text
    assert "无法核实" in text


async def test_url_detection() -> None:
    assert is_http_url("https://a.example")
    assert is_http_url("http://a.example")
    assert not is_http_url("a.example")


async def test_read_question_shapes() -> None:
    with_article = build_read_question(
        "https://a.example/x", "标题: T\n正文:\nBODY", 100
    )
    assert "BODY" in with_article
    # 正文超长时按上限截断
    clipped = build_read_question("https://a.example/x", "B" * 50, 10)
    assert "B" * 50 not in clipped
    assert "B" * 10 in clipped
    # 预抓取失败时让模型自己抓
    fetch_hint = build_read_question("https://a.example/x", "", 10)
    assert "fetch_page" in fetch_hint
    pasted = build_read_question("一段正文" * 100, "", 50)
    assert len(pasted) < 200
