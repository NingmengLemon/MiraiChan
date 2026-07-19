from datetime import date
from typing import Literal, TypedDict

from aiohttp import ClientSession
from lemony_network.request import HTTP_HEADERS
from pydantic import TypeAdapter

CNEB_API = "https://gdapi.cnr.cn/yjwnews"

type AlertLevel = Literal["红色预警", "橙色预警", "黄色预警", "蓝色预警"]
ALL_LEVELS: set[AlertLevel] = set(AlertLevel.__value__.__args__)
# joined with ; when sending request


class AlertItem(TypedDict):
    docid: int
    doccontent: str
    docabstract: str
    chnlname: str
    channelid: str
    doctitle: str
    docpubtime: str
    docpuburl: str
    parentId: str
    modelType: int
    icon: str
    iconDesc: str


class AlertListResponse(TypedDict):
    datas: list[AlertItem]
    sums: int
    status: int
    message: str


alert_list_response_adapter = TypeAdapter(AlertListResponse)


async def fetch(
    client: ClientSession,
    *,
    levels: set[AlertLevel] | None = None,
    province: str | None = None,
    city: str | None = None,
    start_time: date | None = None,
    end_time: date | None = None,
    kw: str | None = None,
    page: int = 1,
    page_size: int = 15,
):
    payload = {
        "from": "",
        "keyword": kw if kw else "",
        "province": province if province else "",
        "city": city if city else "",
        "level": ";".join(levels) if levels else "",
        "starttime": start_time.isoformat() if start_time else "",
        "endtime": end_time.isoformat() if end_time else "",
        "page": page,
        "size": str(page_size),
    }
    async with client.post(CNEB_API, json=payload, headers=HTTP_HEADERS) as response:
        data = await response.json()
    return alert_list_response_adapter.validate_python(data)
