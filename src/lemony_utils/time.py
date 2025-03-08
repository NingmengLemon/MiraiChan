import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, TypedDict
from weakref import WeakSet

from melobot.typ import AsyncCallable


class GapTimer:
    def __init__(self):
        self._start: int | None = None
        self._end: int | None = None

    def __enter__(self):
        self._start = time.perf_counter_ns()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._end = time.perf_counter_ns()

    @property
    def result_ns(self):
        if self._start is None or self._end is None:
            return None
        return self._end - self._start

    @property
    def result_us(self):
        r = self.result_ns
        return None if r is None else r / 10**3

    @property
    def result_ms(self):
        r = self.result_ns
        return None if r is None else r / 10**6

    @property
    def result_s(self):
        r = self.result_ns
        return None if r is None else r / 10**9


def get_time_period_start(
    period: Literal["day", "month", "year"], time_input: float | datetime | None = None
):
    if time_input is None:
        dt = datetime.now()
    elif isinstance(time_input, (float, int)):
        dt = datetime.fromtimestamp(time_input)
    elif isinstance(time_input, datetime):
        dt = time_input
    else:
        raise TypeError(
            f"timestamp or datetime obj expected, {type(time_input)!r} given"
        )

    if period == "day":
        new_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        new_dt = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "year":
        new_dt = dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Invalid period: {period}")

    return new_dt
