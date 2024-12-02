import asyncio

from lxml import etree

from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers
from .models import ItemsLib

__all__ = [
    "fetch",
]

URL = "https://prts.wiki/w/%E9%81%93%E5%85%B7%E4%B8%80%E8%A7%88"
XPATH_DATA = '//div[@class="smwdata"]'


async def fetch():
    async with async_http(URL, "get", headers=http_headers) as resp:
        resp.raise_for_status()
        return await asyncio.to_thread(extract, await resp.text())


def extract(htmltext: str):
    html = etree.HTML(htmltext, etree.HTMLParser())
    return ItemsLib(data=[_standize_one(i.attrib) for i in html.xpath(XPATH_DATA)])


def _standize_one(item: dict[str, str]):
    item = {k.removeprefix("data-"): v for k, v in item.items() if k != "class"}
    item.update(
        {
            "category": [
                i.strip().removeprefix("分类:") for i in item["category"].split(",")
            ]
        }
    )
    return item
