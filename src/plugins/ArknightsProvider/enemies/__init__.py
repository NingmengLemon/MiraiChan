import asyncio
import json

from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers

from .models import Enemy, EnemyLib

__all__ = [
    "fetch",
]

URL = "https://prts.wiki/index.php?title=%E6%95%8C%E4%BA%BA%E4%B8%80%E8%A7%88%2F%E6%95%B0%E6%8D%AE&action=raw&ctype=application%2Fjson"


async def fetch():
    async with async_http(URL, "get", headers=http_headers) as resp:
        resp.raise_for_status()
        # return await asyncio.to_thread(
        #     lambda t: EnemyLib(data=json.loads(t)),
        #     await resp.text(),
        # )
        return EnemyLib(data=json.loads(await resp.text()))
