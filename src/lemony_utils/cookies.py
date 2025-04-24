from collections.abc import Iterable
from http.cookies import Morsel
from typing import TypedDict

from aiohttp.cookiejar import CookieJar


class _DictedCookieItem(TypedDict):
    key: str
    value: str
    metadata: dict[str, str]


def cookiedicts_from_session(cj: CookieJar):
    """产生的东西可以序列化成JSON也可以递给 cookiedicts_to_morsels"""
    result: list[_DictedCookieItem] = []
    for cookie in cj:
        result.append(
            {"key": cookie.key, "value": cookie.value, "metadata": dict(cookie)}
        )
    return result


def cookiedicts_to_morsels(cookies: Iterable[_DictedCookieItem]):
    """产生的东西可以递给 loadable_tuples_from_morsels"""
    result: list[Morsel[str]] = []
    for cookie in cookies:
        ms = Morsel()
        ms.set(cookie["key"], cookie["value"], cookie["value"])
        ms.update(cookie["metadata"])
        result.append(ms)
    return result


def loadable_tuples_from_morsels(morsels: Iterable[Morsel]):
    """产生的东西可以递给 ClientSession 初始化方法的 cookies 参数"""
    return ((m.key, m) for m in morsels)
