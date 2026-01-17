import functools
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Literal, NotRequired, Optional

from aiohttp import ClientResponse, ClientSession, TCPConnector
from aiohttp.client import _RequestOptions
from melobot.typ import AsyncCallable
from yarl import URL

from .qqntimg_sslcontext import SSL_CONTEXT

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


@asynccontextmanager
async def async_http(
    url: UrlStr,
    method: Literal["get", "post"],
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    json: Optional[dict] = None,
    **kwargs,
) -> AsyncGenerator[ClientResponse, None]:
    async with ClientSession(
        headers=headers, connector=TCPConnector(ssl=SSL_CONTEXT)
    ) as http_session:
        if json:
            kwargs["json"] = json
        if params:
            kwargs["params"] = params
        if method == "get":
            async with http_session.get(url, **kwargs) as resp:
                yield resp
        else:
            async with http_session.post(url, data=data, **kwargs) as resp:
                yield resp


@asynccontextmanager
async def dummy_session_context(session: ClientSession):
    yield session


class _ReqTemplateDecoratedReturn(_RequestOptions):
    method: NotRequired[Literal["get", "post"]]


def async_reqtemplate(
    handle: Literal["json", "bytes", "str"] = "json",
):
    def decorator(
        func: AsyncCallable[..., tuple[UrlStr, _ReqTemplateDecoratedReturn] | UrlStr],
    ):
        @functools.wraps(func)
        async def wrapper(session: ClientSession | None = None, **kwargs):
            if isinstance(_ := await func(**kwargs), tuple):
                url, reqargs = _
            else:
                url, reqargs = _, {}
            reqargs.setdefault("method", "get")
            async with (
                ClientSession(
                    headers=http_headers, connector=TCPConnector(ssl=SSL_CONTEXT)
                )
                if session is None
                else dummy_session_context(session)
            ) as session:
                async with session.request(url=url, **reqargs) as resp:
                    match handle:
                        case "json":
                            return await resp.json()
                        case "bytes":
                            return await resp.read()
                        case "str":
                            return await resp.text(encoding="utf-8")

        return wrapper

    return decorator
