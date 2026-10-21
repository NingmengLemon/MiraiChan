"""把一条消息里的卡片/短链翻成回复文本

纯逻辑: 取链接、交给 ``resolve`` 跟随重定向、可选地再问 ``brief`` 要标题,
最后由 :func:`render` 拼成一两句。发请求的部分在 :mod:`resolve` 里。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .links import card_url, extract_short_links, is_mikufans_url, strip_tracking
from .resolve import Brief, Resolve, bvid_of

__all__ = ["Resolution", "analyse", "render"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Resolution:
    original: str
    resolved: str
    brief: str | None = None


async def analyse(
    text: str,
    cards: Sequence[Mapping[str, object]],
    *,
    resolve: Resolve,
    brief: Brief | None,
    max_items: int = 1,
) -> list[Resolution]:
    """从正文短链与卡片里挑出要处理的链接, 逐个解析"""
    candidates: list[str] = []
    for payload in cards:
        url = card_url(payload)
        if url:
            candidates.append(url)
    candidates.extend(extract_short_links(text))

    # 同一地址在卡片与正文里写法可能不同, 归一化后再去重; 保留第一次出现的原文用于比较
    seen: dict[str, str] = {}
    for url in candidates:
        if not is_mikufans_url(url):
            continue
        seen.setdefault(strip_tracking(url), url)
        if len(seen) >= max_items:
            break

    results: list[Resolution] = []
    for url in seen.values():
        resolved = await resolve(url)
        detail = None
        if brief is not None and (bvid := bvid_of(resolved)):
            try:
                detail = await brief(bvid)
            except Exception:
                logger.warning("取摘要失败: %s", bvid, exc_info=True)
        results.append(Resolution(original=url, resolved=resolved, brief=detail))
    return results


def render(results: Sequence[Resolution], *, plain: bool = False) -> str | None:
    """拼回复; 没有可回的内容时返回 None

    ``plain`` 表示没装详情 SDK: 只回净化后的链接; 原文本来就是干净链接时不回, 免得刷屏。
    """
    lines: list[str] = []
    for item in results:
        if item.brief:
            lines.append(f"{item.brief}\n{item.resolved}")
        elif plain:
            if item.original != item.resolved:
                lines.append(item.resolved)
        else:
            lines.append(item.resolved)
    return "\n".join(lines) if lines else None
