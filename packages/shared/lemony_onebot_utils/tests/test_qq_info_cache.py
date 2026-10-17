"""QQInfoCache: 命中 / 过期 / 失败缓存 / 并发合并 / 超时 / 容量淘汰"""

import asyncio
from typing import Any

import pytest
from lemony_onebot_utils.qq import MemberInfo, QQInfoCache


class _Echo:
    def __init__(self, data: Any, ok: bool = True) -> None:
        self.data = data
        self._ok = ok

    def is_ok(self) -> bool:
        return self._ok


class FakeAdapter:
    """模仿 melobot 的 ``await (await adapter.xxx(...)))[0]`` 调用形状"""

    def __init__(self, members: dict[int, dict], *, delay: float = 0.0) -> None:
        self.members = members
        self.delay = delay
        self.calls: list[tuple[int, int]] = []

    async def get_group_member_info(self, group_id: int, user_id: int):
        self.calls.append((group_id, user_id))

        async def handles():
            if self.delay:
                await asyncio.sleep(self.delay)
            data = self.members.get(user_id)
            return [_Echo(data, ok=data is not None)]

        return handles()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


MEMBERS = {
    1: {"nickname": "甲昵称", "card": "甲名片", "role": "admin"},
    2: {"nickname": "乙昵称", "card": ""},
}


def test_member_hit_and_display_name() -> None:
    adapter = FakeAdapter(MEMBERS)
    cache = QQInfoCache()

    async def run():
        a = await cache.member(adapter, 10, 1)
        b = await cache.member(adapter, 10, 2)
        again = await cache.member(adapter, 10, 1)
        return a, b, again

    a, b, again = asyncio.run(run())
    assert a == MemberInfo(10, 1, "甲昵称", "甲名片", role="admin")
    assert a.display_name == "甲名片"
    assert b is not None and b.display_name == "乙昵称"
    assert again is a
    assert adapter.calls == [(10, 1), (10, 2)]


def test_ttl_expiry_and_negative_cache() -> None:
    adapter = FakeAdapter(MEMBERS)
    clock = Clock()
    cache = QQInfoCache(ttl=100, negative_ttl=10, clock=clock)

    async def run():
        assert await cache.member(adapter, 10, 1) is not None
        assert await cache.member(adapter, 10, 9) is None  # 不存在的成员
        clock.now += 5
        await cache.member(adapter, 10, 1)
        await cache.member(adapter, 10, 9)  # 失败结果仍在缓存期内
        clock.now += 10
        await cache.member(adapter, 10, 9)  # 失败缓存过期, 重查
        clock.now += 100
        await cache.member(adapter, 10, 1)  # 命中缓存过期, 重查

    asyncio.run(run())
    assert adapter.calls == [(10, 1), (10, 9), (10, 9), (10, 1)]


def test_concurrent_requests_share_one_action() -> None:
    adapter = FakeAdapter(MEMBERS, delay=0.05)
    cache = QQInfoCache()

    async def run():
        return await asyncio.gather(*(cache.member(adapter, 10, 1) for _ in range(5)))

    results = asyncio.run(run())
    assert len({id(r) for r in results}) == 1
    assert adapter.calls == [(10, 1)]


def test_timeout_returns_none_and_is_cached() -> None:
    adapter = FakeAdapter(MEMBERS, delay=1.0)
    cache = QQInfoCache(timeout=0.05)

    async def run():
        first = await cache.member(adapter, 10, 1)
        second = await cache.member(adapter, 10, 1)
        return first, second

    assert asyncio.run(run()) == (None, None)
    assert adapter.calls == [(10, 1)]


def test_members_batch_limit_and_missing() -> None:
    adapter = FakeAdapter(MEMBERS)
    cache = QQInfoCache()
    found = asyncio.run(cache.members(adapter, 10, [2, 1, 9, 1]))
    assert set(found) == {1, 2}
    limited = asyncio.run(QQInfoCache().members(adapter, 10, [3, 2, 1], limit=2))
    assert set(limited) == {1, 2}


def test_remember_and_invalidate() -> None:
    adapter = FakeAdapter(MEMBERS)
    cache = QQInfoCache()
    cache.remember_member(10, 5, nickname="戊", card=None)
    cache.remember_member(10, 6, nickname=None, card=None)  # 没有信息, 不写

    async def run():
        five = await cache.member(adapter, 10, 5)
        cache.invalidate_member(10, 5)
        after = await cache.member(adapter, 10, 5)
        return five, after

    five, after = asyncio.run(run())
    assert five is not None and five.display_name == "戊"
    assert after is None  # 失效后真的去查了, 假实现端里没有 5
    assert adapter.calls == [(10, 5)]


def test_max_entries_evicts_least_recently_used() -> None:
    adapter = FakeAdapter(MEMBERS)
    cache = QQInfoCache(max_entries=2)

    async def run():
        await cache.member(adapter, 10, 1)
        await cache.member(adapter, 10, 2)
        await cache.member(adapter, 10, 1)  # 1 变成最近使用
        await cache.member(adapter, 10, 9)  # 淘汰 2
        await cache.member(adapter, 10, 1)
        await cache.member(adapter, 10, 2)

    asyncio.run(run())
    assert adapter.calls == [(10, 1), (10, 2), (10, 9), (10, 2)]


def test_action_exception_is_swallowed() -> None:
    class Broken:
        async def get_group_member_info(self, group_id: int, user_id: int):
            raise RuntimeError("boom")

    assert asyncio.run(QQInfoCache().member(Broken(), 10, 1)) is None


@pytest.mark.parametrize("card", ["", "  "])
def test_display_name_falls_back(card: str) -> None:
    assert MemberInfo(1, 7, "", card).display_name == "7"
