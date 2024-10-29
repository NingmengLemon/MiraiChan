import functools
from typing import Callable, Literal, NotRequired
from contextlib import asynccontextmanager

from aiohttp import ClientSession
from aiohttp.client import _RequestOptions
from melobot.typ import AsyncCallable
from yarl import URL

from .consts import http_headers


@asynccontextmanager
async def dummy_session_context(session: ClientSession):
    yield session


class _ReqTemplateDecoratedReturn(_RequestOptions):
    url: str | URL
    method: NotRequired[Literal["get", "post"]]


def async_reqtemplate(
    handle: Literal["json", "bytes", "str"] = "json",
):
    def decorator(func: AsyncCallable[..., _ReqTemplateDecoratedReturn]):
        @functools.wraps(func)
        async def wrapper(session: ClientSession | None = None, **kwargs):
            reqargs = await func(**kwargs)
            reqargs.setdefault("method", "get")
            async with (
                ClientSession() if session is None else dummy_session_context(session)
            ) as session:
                async with session.request(**reqargs) as resp:
                    match handle:
                        case "json":
                            return await resp.json()
                        case "bytes":
                            return await resp.read()
                        case "str":
                            return await resp.text(encoding="utf-8")

        return wrapper

    return decorator
