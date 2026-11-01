from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Unpack,
)

from aiohttp import (
    ClientResponse,
    ClientSession,
    ClientTimeout,
)
from aiohttp.client import _RequestOptions
from yarl import URL

from .qqntmedia_sslcontext import QQNTMEDIA_SSL_CONTEXT

UrlStr = URL | str
_HTTP_HEADERS = {
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
HTTP_HEADERS = MappingProxyType(_HTTP_HEADERS)

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


class ResponseTooLargeError(ValueError):
    """响应体超过调用方给出的上限"""


async def download_bytes(
    session: ClientSession,
    url: UrlStr,
    *,
    max_bytes: int,
    total_timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
) -> bytes:
    """下载完整响应体并限制大小; QQ NT 图床自动使用专用 TLS 配置."""
    ssl = QQNTMEDIA_SSL_CONTEXT if "multimedia.nt.qq.com.cn" in str(url) else True
    kwargs: dict[str, Any] = {"ssl": ssl}
    if total_timeout is not None:
        kwargs["timeout"] = ClientTimeout(total=total_timeout)
    if headers is not None:
        kwargs["headers"] = dict(headers)
    async with async_http(session=session, method="get", url=url, **kwargs) as response:
        if (response.content_length or 0) > max_bytes:
            raise ResponseTooLargeError(
                f"response exceeds max size: {response.content_length} > {max_bytes}"
            )
        buffer = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise ResponseTooLargeError(f"response exceeds max size: > {max_bytes}")
        return bytes(buffer)
