from typing import Callable, Literal, Optional, Union
import json
import logging

request: Callable = None
update_baseline = 0  # bassline (大雾)
offset = 0


async def get_new() -> list[dict]:
    global update_baseline
    global offset
    try:
        data: dict = get_dynamic_list(offset=offset, update_baseline=update_baseline)
    except Exception as e:
        logging.exception(e)
        return []
    else:
        if offset == update_baseline == 0:
            # 初始化用
            offset = data.get("offset", 0)
            update_baseline = data.get("update_baseline", 0)
            return []
        else:
            return data["items"][: data["update_num"]]


async def get_dynamic_list(
    type_: Literal["all", "video", "pgc", "article"] = "all",
    offset: Optional[Union[str, int]] = None,
    update_baseline: Optional[Union[str, int]] = None,
):
    """
    需要登录

    results:
    [
    dy 1 <- id: {update_baseline} (在请求中传入时仅作统计用)
    dy 2
    dy 3
    ...
    dy n <- id: {offset} (在下一次请求中作为传入来实现翻页)
    ]
    """
    api = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
    api += "?timezone_offset=-480&type=%s" % type_
    if offset:
        api += "&offset=%s" % offset
    if update_baseline:
        api += "&update_baseline=%s" % update_baseline

    data: dict = await request(api, mod="get", return_type="dict")
    assert data["code"] == 0, data.get("message")
    data: dict = data["data"]

    result = {
        "has_more": data.get("has_more"),
        "offset": data.get("offset", ""),
        "update_baseline": data.get("update_baseline", ""),
        "update_num": data.get("update_num", 0),  # 在 update_baseline 以上的动态个数
        "items": [generate_card(i) for i in data.get("items", [])],
    }

    return result


def generate_card(item: dict):
    pass