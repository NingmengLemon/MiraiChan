"""决定一条报文推给哪些订阅.

- 同一报 (数据源, 事件, 报数) 只处理一次: 多条 ws 连接或服务端重发都可能带来重复报文
- 太旧的报文不推: 重连、手动查询拿到的往往是早已过去的地震
- 训练报不推
- 每个订阅按更新策略决定一个事件推几次; 事件首次达到阈值时才算"首报",
  所以震级在后续报中上调过线时仍会推送
- 取消报只推给之前收到过该事件的订阅, 不受阈值影响
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .quake import Quake, QuakeKind
from .subscription import Subscription, TargetKey

__all__ = ["Dispatcher"]

_DEFAULT_MAX_AGE: dict[QuakeKind, timedelta] = {
    "eew": timedelta(minutes=10),
    "report": timedelta(hours=1),
}
#: 去重状态保留多久
_RETENTION = timedelta(days=1)


@dataclass(slots=True)
class _Pushed:
    at: datetime
    final: bool = False
    seqs: set[int] = field(default_factory=set)


class Dispatcher:
    def __init__(
        self,
        *,
        max_age: dict[QuakeKind, timedelta] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._max_age = {**_DEFAULT_MAX_AGE, **(max_age or {})}
        self._now = now
        self._seen: dict[tuple[str, str, int], datetime] = {}
        self._pushed: dict[tuple[TargetKey, tuple[str, str]], _Pushed] = {}

    def select(self, quake: Quake, subs: Iterable[Subscription]) -> list[Subscription]:
        """返回需要推送这条报文的订阅, 并记下已推送"""
        now = self._now()
        self._prune(now)
        if quake.report_key in self._seen:
            return []
        self._seen[quake.report_key] = now
        if "训练" in quake.extra_tags:
            return []
        if now - quake.report_time > self._max_age[quake.kind]:
            return []

        chosen: list[Subscription] = []
        for sub in subs:
            key = (sub.target, quake.event_key)
            prev = self._pushed.get(key)
            if self._should_push(sub, quake, prev):
                chosen.append(sub)
                rec = prev or self._pushed.setdefault(key, _Pushed(at=now))
                rec.at = now
                rec.final = rec.final or quake.is_final or quake.is_cancel
                rec.seqs.add(quake.seq)
        return chosen

    @staticmethod
    def _should_push(sub: Subscription, quake: Quake, prev: _Pushed | None) -> bool:
        if not sub.enabled:
            return False
        if quake.is_cancel:
            return prev is not None and quake.kind in sub.kinds
        if not sub.matches(quake):
            return False
        if prev is None:
            return True
        match sub.updates:
            case "all":
                return True
            case "final":
                return quake.is_final and not prev.final
            case "first":
                return False

    def _prune(self, now: datetime) -> None:
        cutoff = now - _RETENTION
        self._seen = {k: t for k, t in self._seen.items() if t >= cutoff}
        self._pushed = {k: v for k, v in self._pushed.items() if v.at >= cutoff}
