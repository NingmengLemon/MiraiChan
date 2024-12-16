import json
from typing import Any

from melobot.plugin import PluginPlanner
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.protocols.onebot.v11.adapter.segment import JsonSegment
from yarl import URL

from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http

Purifier = PluginPlanner("0.1.0")


async def redirect_url(u: URL | str):
    async with async_http(u, "get", headers=http_headers, allow_redirects=True) as resp:
        resp.raise_for_status()
        return resp.url


async def purify_biliurl(u: URL | str):
    u = await redirect_url(u)
    return str(u.with_query(None))


@Purifier.use
@on_message()
async def unpack_cardmsg(event: MessageEvent, adapter: Adapter, logger: GenericLogger):
    jsegs = [s for s in event.message if isinstance(s, JsonSegment)]
    if not jsegs:
        return
    jseg = jsegs[0]
    data: dict[str, Any] = json.loads(jseg.data["data"])
    url = data.get("meta", {}).get("detail_1", {}).get("qqdocurl") or data.get(
        "meta", {}
    ).get("news", {}).get("jumpUrl")
    logger.debug(f"extract url: {url}")
    if url and ("b23.tv" in url or "bilibili.com" in url):
        url = await purify_biliurl(url)
        logger.debug(f"url purified: {url}")
        await adapter.send_reply(url)
