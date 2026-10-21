"""mikufans 链接与卡片解析

纯函数 + 假实现, 不发真实请求, 也不依赖私有 SDK 是否安装。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from mbplugin_mikufans.links import (
    card_url,
    extract_short_links,
    is_mikufans_url,
    kept_params,
    strip_tracking,
)
from mbplugin_mikufans.pipeline import Resolution, analyse, render
from mbplugin_mikufans.resolve import bvid_of, make_brief

CARD_QQDOC = {
    "app": "com.tencent.miniapp_01",
    "meta": {"detail_1": {"qqdocurl": "https://b23.tv/AbCd12?share=1"}},
}
CARD_NEWS = {
    "meta": {"news": {"jumpUrl": "https://www.bilibili.com/video/BV1xx411c7mD?spm=1"}}
}
CLEAN = "https://www.bilibili.com/video/BV1xx411c7mD"


def test_card_url_paths() -> None:
    assert card_url(CARD_QQDOC) == "https://b23.tv/AbCd12?share=1"
    assert card_url(CARD_NEWS) == "https://www.bilibili.com/video/BV1xx411c7mD?spm=1"
    assert card_url({"meta": {}}) is None
    assert card_url({"meta": "bad"}) is None
    assert card_url({}) is None
    # 旧实现只认这两个字段, 不认识的路径不猜
    assert card_url({"meta": {"detail_1": {"url": "https://b23.tv/x"}}}) is None


def test_short_link_extraction() -> None:
    text = "看这个 https://b23.tv/abc123 还有 https://b23.tv/abc123 和 https://example.com/x"
    assert extract_short_links(text) == ["https://b23.tv/abc123"]


def test_whitelist_keeps_only_known_params() -> None:
    # p (分 P) 与 t (起播秒数) 有含义, 保留; 没登记的查询参数一律丢掉
    assert (
        strip_tracking(
            "https://www.bilibili.com/video/BV1?p=2&t=75&spm_id_from=333&foo=bar"
        )
        == "https://www.bilibili.com/video/BV1?p=2&t=75"
    )
    # 短链没有任何需要保留的参数
    assert (
        strip_tracking("https://b23.tv/abc?share=1#part") == "https://b23.tv/abc#part"
    )
    # 其它路由各有自己的白名单
    assert (
        strip_tracking("https://search.bilibili.com/all?keyword=t&page=2&spm=1")
        == "https://search.bilibili.com/all?keyword=t&page=2"
    )
    assert (
        strip_tracking("https://space.bilibili.com/1/favlist?fid=9&ctype=1&spm=1")
        == "https://space.bilibili.com/1/favlist?fid=9&ctype=1"
    )
    assert kept_params("https://www.bilibili.com/video/BV1") == frozenset({"p", "t"})
    assert kept_params("https://b23.tv/abc") == frozenset()
    assert is_mikufans_url("https://b23.tv/abc")
    assert is_mikufans_url("https://www.bilibili.com/video/x")
    assert not is_mikufans_url("https://example.com/b23.tv")


def test_bvid_of() -> None:
    assert bvid_of("https://www.bilibili.com/video/BV1xx411c7mD?p=1") == "BV1xx411c7mD"
    assert bvid_of("https://b23.tv/abc") is None


async def _fake_resolve(url: str) -> str:
    return {
        "https://b23.tv/AbCd12?share=1": CLEAN,
        "https://b23.tv/text1": "https://www.bilibili.com/video/BV1yy411c7mE",
    }.get(url, strip_tracking(url))


@pytest.mark.asyncio
async def test_analyse_prefers_card_and_limits() -> None:
    seen: list[str] = []

    async def brief(bvid: str) -> str:
        seen.append(bvid)
        return f"标题 {bvid}"

    results = await analyse(
        "顺便 https://b23.tv/text1",
        [CARD_QQDOC],
        resolve=_fake_resolve,
        brief=brief,
        max_items=1,
    )
    assert len(results) == 1
    assert results[0].resolved == CLEAN
    # 摘要只应该拿到解析后的 bvid
    assert seen == ["BV1xx411c7mD"]


@pytest.mark.asyncio
async def test_analyse_dedupes_card_and_text() -> None:
    # 卡片与正文指向同一个短链 (只差一个 share 参数), 只解析一次
    results = await analyse(
        "https://b23.tv/AbCd12",
        [CARD_QQDOC],
        resolve=_fake_resolve,
        brief=None,
        max_items=2,
    )
    assert len(results) == 1


@pytest.mark.asyncio
async def test_long_card_with_tracking_still_replies() -> None:
    # 默认模式的回归: 长链卡片只有跟踪参数时, 也必须回净化后的链接
    results = await analyse(
        "",
        [CARD_NEWS],
        resolve=_fake_resolve,
        brief=None,
    )
    assert render(results, plain=True) == CLEAN


def test_render_modes() -> None:
    full = Resolution(
        original="https://b23.tv/x?share=1",
        resolved=CLEAN,
        brief="标题 | UP 主 | 123 播放",
    )
    plain = Resolution(original="https://b23.tv/x?share=1", resolved=CLEAN)
    assert render([full]) == f"标题 | UP 主 | 123 播放\n{CLEAN}"
    assert render([plain], plain=True) == CLEAN
    # 原文已经干净时不再复读
    same = Resolution(original=CLEAN, resolved=CLEAN)
    assert render([same], plain=True) is None
    assert render([]) is None


@pytest.mark.asyncio
async def test_brief_failure_does_not_drop_the_reply() -> None:
    async def broken(_bvid: str) -> str | None:
        raise RuntimeError("boom")

    results = await analyse(
        "",
        [CARD_QQDOC],
        resolve=_fake_resolve,
        brief=broken,
    )
    assert results[0].resolved == CLEAN
    assert results[0].brief is None
    assert render(results, plain=False) == CLEAN


def test_brief_absent_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    original = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any):
        if name.startswith("citric_mikufans"):
            raise ImportError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert make_brief() is None


def test_brief_absent_when_sdk_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    original = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any):
        if name.startswith("citric_mikufans"):
            raise OSError("native module cannot load")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert make_brief() is None
