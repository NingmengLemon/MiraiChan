import asyncio
import time
import json
import copy
import os

from lxml import etree

request = None

SOURCE_SHEET = {
    "url": "https://wiki.biligame.com/arknights/%E5%B9%B2%E5%91%98%E6%95%B0%E6%8D%AE%E8%A1%A8",
    "values": {
        "name": {
            "xpath": '//*[@id="CardSelectTr"]/tbody/tr/td[2]/a/text()',
            "extractor": lambda obj: obj.strip(),
        },
        "star": {
            "xpath": '//*[@id="CardSelectTr"]/tbody/tr/td[5]/text()',
            "extractor": lambda obj: int(obj.strip()),
        },
        "prof": {
            "xpath": '//*[@id="CardSelectTr"]/tbody/tr/td[4]/img/@alt',
            "extractor": lambda obj: obj.strip(),
        },
        "pool": {
            "xpath": '//*[@id="CardSelectTr"]/tbody/tr/td[8]',
            "extractor": lambda obj: [i.strip() for i in obj.xpath("./text()") if bool(i.strip())],
        },
    },
}

data_file = "./data/akoperators.json"
operator_lib = []


def save_lib():
    json.dump(operator_lib, open(data_file, "w+", encoding="utf-8"), indent=4, ensure_ascii=False)


def load_lib():
    global operator_lib
    if os.path.exists(data_file):
        operator_lib = json.load(open(data_file, "r", encoding="utf-8"))
    else:
        operator_lib = []


def get_nowait():
    return copy.deepcopy(operator_lib)


async def get():
    global operator_lib
    if not operator_lib:
        operator_lib = await fetch()
    return copy.deepcopy(operator_lib)


async def fetch(sheet=SOURCE_SHEET, data=None):
    url = sheet.get("url")
    values = sheet.get("values")

    if not data:
        data = await request(url, return_type="str")
    data = etree.HTML(data, etree.HTMLParser())

    columns = {
        k: [(v["extractor"])(i) for i in data.xpath(v["xpath"])]
        for k, v in values.items()
    }
    result = [
        {k: columns[k][i] for k in values.keys()}
        for i in range(len(columns[list(values.keys())[0]]))
    ]
    # for i in result:
    #     print(i)
    return result

load_lib()


if __name__ == "__main__":
    with open("./plugins/ArknightsGacha/sample.html", "r", encoding="utf-8") as f:
        data = f.read()
    operator_lib = asyncio.run(fetch(data=data))
    save_lib()
