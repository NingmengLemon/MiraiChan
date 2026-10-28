"""核验插件的运行期状态: 冷却、图片级去重与缓存

放在单独模块里是为了能脱离 bot 实例测试: 入口模块 import 时就要 `get_bot()`,
测试没法直接导入。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from .client import ProvenanceResult

__all__ = [
    "AccessLevel",
    "CachedCheck",
    "CheckRegistry",
    "Cooldown",
    "access_level",
]

#: 指令的开放范围; ``all`` 是给普通用户开放的模式, 默认不走
AccessLevel = Literal["all", "admins", "owner"]


def access_level(allow_all: bool, allow_admins: bool) -> AccessLevel:
    """谁能用核验指令: 全部用户 / owner 与管理员 / 仅 owner"""
    if allow_all:
        return "all"
    return "admins" if allow_admins else "owner"


class Cooldown:
    """每条命令成功进入后记一次时间, ``remaining`` 返回还要等多少秒"""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._last: dict[int, float] = {}

    def touch(self, user_id: int, *, now: float | None = None) -> None:
        self._last[user_id] = time.monotonic() if now is None else now

    def remaining(self, user_id: int, *, now: float | None = None) -> float:
        last = self._last.get(user_id)
        if last is None:
            return 0.0
        current = time.monotonic() if now is None else now
        return max(self.seconds - (current - last), 0.0)


@dataclass(frozen=True, slots=True)
class CachedCheck:
    results: tuple[ProvenanceResult, ...]
    checked_at: float


class CheckRegistry:
    """按内容摘要去重: 刚查过的图片直接复用结果, 正在检查的跳过"""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._cache: dict[str, CachedCheck] = {}
        self._running: set[str] = set()

    def cached(
        self, digest: str, *, now: float | None = None
    ) -> tuple[ProvenanceResult, ...] | None:
        entry = self._cache.get(digest)
        if entry is None:
            return None
        current = time.monotonic() if now is None else now
        if current - entry.checked_at > self.ttl:
            self._cache.pop(digest, None)
            return None
        return entry.results

    def begin(self, digest: str) -> bool:
        """占住一张图; 已经在检查时返回 False"""
        if digest in self._running:
            return False
        self._running.add(digest)
        return True

    def finish(
        self,
        digest: str,
        results: tuple[ProvenanceResult, ...] | None = None,
        *,
        now: float | None = None,
    ) -> None:
        """结束占位; 有结果才写缓存, 失败不缓存"""
        current = time.monotonic() if now is None else now
        self._running.discard(digest)
        if results is None:
            return
        self._cache[digest] = CachedCheck(results=results, checked_at=current)
        self._prune(now=current)

    def _prune(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        stale = [
            digest
            for digest, entry in self._cache.items()
            if current - entry.checked_at > self.ttl
        ]
        for digest in stale:
            self._cache.pop(digest, None)
