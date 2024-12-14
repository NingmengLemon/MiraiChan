from contextlib import asynccontextmanager
from io import BytesIO
from typing import Literal
import uuid

import aiohttp
import yarl

from lemony_utils.templates import async_http


class TmpfileHost:
    def __init__(self, access_token: str, endpoint: str = "http://127.0.0.1:8000"):
        self._headers = {"Authorization": f"{access_token}"}
        self._endpoint = yarl.URL(endpoint)

    async def upload(self, filename: str, data: BytesIO | bytes) -> str:
        if isinstance(data, BytesIO):
            data = data.getvalue()
        form = aiohttp.FormData()
        form.add_field("file", data, filename=filename)
        async with async_http(
            self._endpoint.joinpath("upload"), "post", data=form, headers=self._headers
        ) as resp:
            resp.raise_for_status()
            return (await resp.json())["path"]

    async def delete(self, path: str) -> Literal["ok"]:
        async with async_http(
            self._endpoint.joinpath("delete"),
            "post",
            json={"path": path},
            headers=self._headers,
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def listdir(self) -> list[str]:
        async with async_http(
            self._endpoint.joinpath("files"), "post", headers=self._headers
        ) as resp:
            resp.raise_for_status()
            return (await resp.json())["files"]

    def download(self, path):
        return async_http(
            self._endpoint.joinpath("download"),
            "get",
            json={"path": path},
            headers=self._headers,
        )

    @asynccontextmanager
    async def tmpsession(self, filename: str | None, data: BytesIO | bytes):
        if not filename:
            filename = uuid.uuid4().hex
        path = None
        try:
            path = await self.upload(filename, data)
            yield path
        finally:
            if path:
                await self.delete(path)
