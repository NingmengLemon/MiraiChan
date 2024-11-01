import functools
from typing import Callable, Literal, NotRequired, AsyncGenerator, Optional
from contextlib import asynccontextmanager

from aiohttp import ClientSession, ClientResponse
from aiohttp.client import _RequestOptions
from melobot.typ import AsyncCallable
from yarl import URL

from .consts import http_headers


@asynccontextmanager
async def async_http(
    url: str,
    method: Literal["get", "post"],
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    json: Optional[dict] = None,
) -> AsyncGenerator[ClientResponse, None]:
    async with ClientSession(headers=headers) as http_session:
        kwargs = {}
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


UrlStr = URL | str


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
                ClientSession(headers=http_headers)
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
