import asyncio
import json

from lxml import etree

from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers

from .models import OperatorLib, OperatorFilters

__all__ = [
    "fetch",
]


URL = "https://prts.wiki/w/%E5%B9%B2%E5%91%98%E4%B8%80%E8%A7%88"
XPATH_DATA = '//*[@id="filter-data"]'
XPATH_FILTER = '//*[@id="filter-filter"]'


async def fetch():
    async with async_http(URL, "get", headers=http_headers) as resp:
        resp.raise_for_status()
        return await asyncio.to_thread(extract, await resp.text())


def extract(htmltext: str):
    html = etree.HTML(htmltext, etree.HTMLParser())
    items: list[etree._Element] = html.xpath(XPATH_DATA)[0].getchildren()
    return (
        OperatorLib(data=[_extract_one(i) for i in items]),
        OperatorFilters.model_validate_json(html.xpath(XPATH_FILTER)[0].text),
    )


def _extract_one(element: etree._Element):
    data = {k.removeprefix("data-"): v for k, v in element.attrib.items()}
    data.update(
        {
            "re_deploy": data["re_deploy"].removesuffix("s"),
            "interval": data["interval"].removesuffix("s"),
            "obtain_method": data["obtain_method"].split(","),
            "cost": data["cost"].split("→"),
            "block": data["block"].split("→"),
        }
    )
    return data
