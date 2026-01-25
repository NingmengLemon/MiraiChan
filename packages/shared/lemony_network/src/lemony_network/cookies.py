from collections.abc import Generator, Iterable
from http.cookies import Morsel
from typing import Any, TypedDict

from aiohttp.cookiejar import CookieJar


class DictedCookieItem(TypedDict):
    key: str
    value: str
    metadata: dict[str, str]


class UniversalCookieJar:
    def __init__(self) -> None:
        self._cookies: list[DictedCookieItem] = []

    @classmethod
    def from_cookiedicts(
        cls, cookies: Iterable[DictedCookieItem]
    ) -> "UniversalCookieJar":
        obj = cls()
        obj._cookies = list(cookies)
        return obj

    @classmethod
    def from_morsels(cls, morsels: Iterable[Morsel]) -> "UniversalCookieJar":
        cookiedicts = cookiedicts_from_morsels(morsels)
        return cls.from_cookiedicts(cookiedicts)

    @classmethod
    def from_aiohttp_cookiejar(cls, cj: CookieJar) -> "UniversalCookieJar":
        cookiedicts = cookiedicts_from_session(cj)
        return cls.from_cookiedicts(cookiedicts)

    def to_morsels(self) -> list[Morsel[str]]:
        return morsels_from_cookiedicts(self._cookies)

    def to_loadable_tuples(self) -> Generator[tuple[str, Morsel[Any]], None, None]:
        morsels = self.to_morsels()
        return loadable_tuples_from_morsels(morsels)

    def to_aiohttp_cookiejar(self) -> CookieJar:
        cj = CookieJar()
        cj.update_cookies(self.to_loadable_tuples())
        return cj

    def to_cookiedicts(self) -> list[DictedCookieItem]:
        return self._cookies.copy()


def cookiedicts_from_morsels(
    morsels: Iterable[Morsel],
) -> list[DictedCookieItem]:
    result: list[DictedCookieItem] = []
    for m in morsels:
        result.append({"key": m.key, "value": m.value, "metadata": dict(m)})
    return result


def cookiedicts_from_session(cj: CookieJar) -> list[DictedCookieItem]:
    result: list[DictedCookieItem] = []
    for cookie in cj:
        result.append(
            {"key": cookie.key, "value": cookie.value, "metadata": dict(cookie)}
        )
    return result


def morsels_from_cookiedicts(cookies: Iterable[DictedCookieItem]) -> list[Morsel[str]]:
    result: list[Morsel[str]] = []
    for cookie in cookies:
        ms = Morsel()
        ms.set(cookie["key"], cookie["value"], cookie["value"])
        ms.update(cookie["metadata"])
        result.append(ms)
    return result


def loadable_tuples_from_morsels(
    morsels: Iterable[Morsel],
) -> Generator[tuple[str, Morsel[Any]], None, None]:
    return ((m.key, m) for m in morsels)
