from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Unpack,
)

from aiohttp import (
    ClientResponse,
    ClientSession,
)
from aiohttp.client import _RequestOptions
from yarl import URL

UrlStr = URL | str
http_headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Dnt": "1",
    "Priority": "u=0, i",
    "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
}


if TYPE_CHECKING:
    from aiohttp.client import _RequestOptions

    type _ReqParams = _RequestOptions

else:
    type _ReqParams = dict[str, Any]


@asynccontextmanager
async def async_http(
    session: ClientSession,
    method: Literal["get", "post"],
    url: UrlStr,
    **kwargs: Unpack[_ReqParams],
) -> AsyncGenerator[ClientResponse, None]:
    async with session.request(method, str(url), **kwargs) as response:
        response.raise_for_status()
        yield response


async def fetch_json(
    session: ClientSession,
    method: Literal["get", "post"],
    url: UrlStr,
    **kwargs: Unpack[_ReqParams],
) -> Any:
    async with async_http(session=session, method=method, url=url, **kwargs) as resp:
        return await resp.json()
