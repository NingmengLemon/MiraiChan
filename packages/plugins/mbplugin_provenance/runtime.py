"""核验插件的运行期状态

放在单独模块里是为了能脱离 bot 实例测试: 入口模块 import 时就要 `get_bot()`,
测试没法直接导入。
"""

from __future__ import annotations

import time

__all__ = ["Cooldown", "InFlight"]


class InFlight:
    """按用户去重: 同一个人的上一条核验没结束时, 新请求直接拒绝"""

    def __init__(self) -> None:
        self._users: set[int] = set()

    def try_enter(self, user_id: int) -> bool:
        if user_id in self._users:
            return False
        self._users.add(user_id)
        return True

    def leave(self, user_id: int) -> None:
        self._users.discard(user_id)

    def __contains__(self, user_id: object) -> bool:
        return user_id in self._users


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
