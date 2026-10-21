"""链接与卡片的纯函数处理

这里只做字符串与 JSON 层面的判断, 不发请求:
- 小程序卡片里取出跳转链接 (旧实现从 ``meta.detail_1.qqdocurl`` 与 ``meta.news.jumpUrl`` 取)
- 正文里的短链抽取
- 去掉跟踪参数
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import (
    SplitResult,
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

__all__ = [
    "card_url",
    "extract_short_links",
    "is_mikufans_url",
    "kept_params",
    "strip_tracking",
]

#: 站点域名。代码与文档一律用 mikufans 代称这个站点, 这些字符串只用于识别链接。
SITE_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn", "bili22.cn")

#: 短链的形态: 域名后的第一段是不带点的短码
_SHORT_RE = re.compile(
    r"https?://(?:b23\.tv|bili2233\.cn|bili22\.cn)/[A-Za-z0-9]+", re.IGNORECASE
)


#: 白名单: 每种资源路径下允许保留的查询参数, 其余一律当跟踪参数丢掉。
#: 上游随时会新长跟踪参数, 用黑名单永远追不完; 新参数要先在这里登记才会被保留。
_PARAMS_BY_ROUTE: dict[str, frozenset[str]] = {
    # 视频: 分 P 与起播秒数
    "video": frozenset({"p", "t"}),
    # 番剧 / 课程: 同上, 外加选集编号
    "bangumi": frozenset({"p", "t", "ep"}),
    "cheese": frozenset({"p", "t", "ep"}),
    # 个人空间的收藏夹与投稿筛选
    "space": frozenset({"fid", "ctype", "type", "tid", "page", "keyword"}),
    # 站内搜索
    "search": frozenset({"keyword", "search_type", "page", "order"}),
    # 合集 / 列表页
    "list": frozenset({"type", "keyword", "page", "sort"}),
}

#: 站点域名。代码与文档一律用 mikufans 代称这个站点, 这些字符串只用于识别链接。
SITE_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn", "bili22.cn")

#: 短链的形态: 域名后的第一段是不带点的短码
_SHORT_RE = re.compile(
    r"https?://(?:b23\.tv|bili2233\.cn|bili22\.cn)/[A-Za-z0-9]+", re.IGNORECASE
)


def is_mikufans_url(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return any(host == suffix or host.endswith("." + suffix) for suffix in SITE_HOSTS)


def _route(parts: SplitResult) -> str:
    """把链接归到一条路由上, 决定保留哪些查询参数"""
    host = (parts.hostname or "").lower()
    if host == "search.bilibili.com":
        return "search"
    if host == "space.bilibili.com":
        return "space"
    segment = parts.path.strip("/").split("/", 1)[0]
    return segment if segment in _PARAMS_BY_ROUTE else ""


def kept_params(url: str) -> frozenset[str]:
    """这个链接允许保留的参数名集合 (白名单)"""
    return _PARAMS_BY_ROUTE.get(_route(urlsplit(url)), frozenset())


def strip_tracking(url: str) -> str:
    """只保留白名单里的查询参数, 其余全部丢弃; 路径、锚点与参数顺序不变"""
    parts = urlsplit(url)
    allowed = kept_params(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key in allowed
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )


def extract_short_links(text: str) -> list[str]:
    """正文里的短链, 按出现顺序去重"""
    seen: dict[str, None] = {}
    for match in _SHORT_RE.finditer(text):
        seen.setdefault(match.group(0), None)
    return list(seen)


def _walk(node: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(node, Mapping):
        return None
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def card_url(payload: Mapping[str, Any]) -> str | None:
    """从卡片 JSON 里取出跳转链接, 取不到返回 None

    小程序卡片把链接放在 ``meta`` 下面, 常见路径是 ``detail_1.qqdocurl`` 与
    ``news.jumpUrl``; 两个都没有时返回 None, 不去猜别的字段。
    """
    meta = payload.get("meta")
    if not isinstance(meta, Mapping):
        return None
    for branch in ("detail_1", "news"):
        section = meta.get(branch)
        url = _walk(section, ("qqdocurl", "jumpUrl"))
        if url:
            return url
    return None
