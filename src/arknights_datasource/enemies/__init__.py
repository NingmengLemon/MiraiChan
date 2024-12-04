import json

from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers

from .models import EnemyLib, Enemy

__all__ = ["fetch", "EnemyLib", "Enemy"]

URL = "https://prts.wiki/index.php?title=%E6%95%8C%E4%BA%BA%E4%B8%80%E8%A7%88%2F%E6%95%B0%E6%8D%AE&action=raw&ctype=application%2Fjson"


async def fetch():
    async with async_http(URL, "get", headers=http_headers) as resp:
        resp.raise_for_status()
        return EnemyLib(data=json.loads(await resp.text()))
