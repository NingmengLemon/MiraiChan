"""lemony_utils 并发工具的单元测试.

回归点: gather_with_concurrency 在 return_exceptions=False 时, 第一个异常抛出后其余任务
继续在后台跑 (asyncio.gather 不会取消兄弟任务), 调用方收尾期间它们还在产生副作用。
"""

from __future__ import annotations

import asyncio

import pytest
from lemony_utils.concurrency import gather_with_concurrency


async def _value(v: int, *, delay: float = 0.0) -> int:
    if delay:
        await asyncio.sleep(delay)
    return v


@pytest.mark.asyncio
async def test_results_keep_input_order() -> None:
    result = await gather_with_concurrency(
        _value(1), _value(2), _value(3), concurrency=2
    )
    assert result == [1, 2, 3]


@pytest.mark.asyncio
async def test_concurrency_is_limited() -> None:
    running = 0
    peak = 0

    async def tracked() -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    await gather_with_concurrency(*[tracked() for _ in range(6)], concurrency=2)
    assert peak <= 2


@pytest.mark.asyncio
async def test_failure_cancels_siblings() -> None:
    """一个任务失败时, 兄弟任务必须被取消, 不能继续在后台跑完."""
    finished: list[int] = []

    async def slow() -> None:
        await asyncio.sleep(0.05)
        finished.append(1)

    async def boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await gather_with_concurrency(slow(), boom(), concurrency=2)

    # 取消是立即的: 等一会儿也不该有兄弟任务跑完
    await asyncio.sleep(0.1)
    assert finished == []


@pytest.mark.asyncio
async def test_return_exceptions_keeps_everything() -> None:
    """return_exceptions=True 时保留原语义: 异常作为结果返回, 兄弟任务照常跑完."""
    finished: list[int] = []

    async def slow() -> str:
        await asyncio.sleep(0.01)
        finished.append(1)
        return "done"

    async def boom() -> str:
        raise RuntimeError("boom")

    result = await gather_with_concurrency(
        slow(), boom(), concurrency=2, return_exceptions=True
    )

    assert result[0] == "done"
    assert isinstance(result[1], RuntimeError)
    assert finished == [1]


@pytest.mark.asyncio
async def test_own_cancellation_still_cleans_up_siblings() -> None:
    """调用方自身被取消时, 兄弟任务也要被取消并等结束."""
    finished: list[int] = []

    async def slow() -> None:
        await asyncio.sleep(0.5)
        finished.append(1)

    task = asyncio.ensure_future(gather_with_concurrency(slow(), slow(), concurrency=2))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.6)
    assert finished == []
