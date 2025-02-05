import functools
from typing import Literal, NotRequired, AsyncGenerator, Optional
from contextlib import asynccontextmanager

from aiohttp import ClientSession, ClientResponse, TCPConnector
from aiohttp.client import _RequestOptions
from melobot.typ import AsyncCallable
from yarl import URL

from .consts import http_headers
from multimedia_sslcontext import SSL_CONTEXT


UrlStr = URL | str


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
        func: AsyncCallable[..., tuple[UrlStr, _ReqTemplateDecoratedReturn] | UrlStr]
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
