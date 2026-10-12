"""冷却与在途去重 (纯逻辑, 注入时钟)。"""

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable

__all__ = ["Cooldown"]


class Cooldown:
    """``{key: 到期时刻}``, 带容量上限 (超出时淘汰最早写入的键)"""

    def __init__(
        self,
        seconds: float,
        *,
        capacity: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._seconds = seconds
        self._capacity = capacity
        self._clock = clock
        self._expires: OrderedDict[Hashable, float] = OrderedDict()

    def remaining(self, key: Hashable) -> float:
        """剩余冷却秒数, 不在冷却中时为 0"""
        expires = self._expires.get(key)
        if expires is None:
            return 0.0
        left = expires - self._clock()
        if left <= 0:
            del self._expires[key]
            return 0.0
        return left

    def touch(self, key: Hashable) -> None:
        if self._seconds <= 0:
            return
        self._expires.pop(key, None)
        self._expires[key] = self._clock() + self._seconds
        while len(self._expires) > self._capacity:
            self._expires.popitem(last=False)

    def __len__(self) -> int:
        return len(self._expires)
