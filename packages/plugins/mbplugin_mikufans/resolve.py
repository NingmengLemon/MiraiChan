"""短链重定向与标题摘要

重定向用 aiohttp; 详情走可选的私有 SDK, 只有装上了才启用。

这里所有"可选能力"都必须自己兜底: SDK 缺文件、二进制加载失败、接口漂移都只让详情降级,
不能让默认的链接净化跟着失效。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from lemony_network.request import HTTP_HEADERS

from .links import is_mikufans_url, strip_tracking

__all__ = ["bvid_of", "make_brief", "make_resolver"]

logger = logging.getLogger(__name__)

_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")

Resolve = Callable[[str], Awaitable[str]]
Brief = Callable[[str], Awaitable[str | None]]


def bvid_of(url: str) -> str | None:
    match = _BVID_RE.search(url)
    return match.group(1) if match else None


def make_resolver(*, timeout: float = 10.0) -> Resolve:
    """返回一个跟随重定向的函数: 输入可能是短链, 输出是去掉跟踪参数的最终地址"""

    import aiohttp

    async def resolve(url: str) -> str:
        if not is_mikufans_url(url):
            return strip_tracking(url)
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with (
            aiohttp.ClientSession(
                timeout=client_timeout, headers=dict(HTTP_HEADERS)
            ) as session,
            # 短链只有 GET 会返回 302, 用 HEAD 常常拿不到跳转
            session.get(url, allow_redirects=True) as response,
        ):
            response.raise_for_status()
            final = str(response.url)
        return strip_tracking(final)

    return resolve


def make_brief(*, timeout: float = 15.0) -> Brief | None:
    """可选的详情摘要: 私有 SDK 不可用时返回 None

    SDK 只在函数内部导入。缺包、二进制加载失败、版本不匹配都算"不可用",
    只有这样默认的链接净化才不会跟着一起坏掉。
    """
    try:
        from citric_mikufans.api.web.video import get_video_detail  # ty: ignore[unresolved-import]
        from citric_mikufans.net.backends.curl_cffi_backend import create_transport  # ty: ignore[unresolved-import]
        from citric_mikufans.net.client import HttpClient  # ty: ignore[unresolved-import]
    except Exception:
        logger.info("详情 SDK 不可用, 只做链接净化", exc_info=True)
        return None

    async def brief(bvid: str) -> str | None:
        try:
            transport = create_transport(timeout=timeout)
            async with HttpClient(transport) as client:
                detail = await client.send(get_video_detail(bvid=bvid))
            parts = [detail.title]
            owner = getattr(detail, "owner", None)
            if owner is not None and getattr(owner, "name", None):
                parts.append(str(owner.name))
            stat = getattr(detail, "stat", None)
            views = getattr(stat, "view", None) if stat is not None else None
            if views is not None:
                parts.append(f"{views} 播放")
        except Exception:
            logger.warning("取视频详情失败: %s", bvid, exc_info=True)
            return None
        return " | ".join(parts)

    return brief
