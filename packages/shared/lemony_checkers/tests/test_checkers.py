"""checkers.py 单元测试 —— melobot Checker 适配层的失败回调.

回归点: FailCallbackMixin 以前把传进来的回调原样保存, 覆盖了 melobot Checker 基类用
to_async 包装好的版本。melobot 的 Checker 允许同步回调, 而原样保存的同步回调在
``await self.fail_cb()`` 时会抛 ``TypeError: object NoneType can't be used in 'await'
expression`` (回调本体已经被调用过了), 该异常被 ``_call_fail_cb`` 吞成一条 error 日志:
每次判定失败都会多出一条"Error in fail callback"的误导性日志。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import MagicMock

import lemony_checkers.checkers as checkers_module
import pytest
from lemony_checkers.checkers import AdminChecker, FailCallbackMixin, OwnerChecker


class _RecordingLogger:
    """记录 error 调用的假日志器."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass


async def _drain(checker: FailCallbackMixin) -> None:
    """等待 fire-and-forget 的失败回调任务跑完."""
    for _ in range(50):
        if not checker._background_tasks:
            return
        await asyncio.sleep(0)
    raise AssertionError("fail callback task did not finish")


class TestFailCallbackMixin:
    """同步与异步回调都要被包装成可 await 的形式."""

    def test_sync_callback_is_wrapped(self):
        """存下来的回调必须是可 await 的 (旧实现存原函数, await 它会抛 TypeError)."""
        mixin = FailCallbackMixin(fail_cb=lambda: None)
        assert mixin.fail_cb is not None
        assert inspect.iscoroutinefunction(mixin.fail_cb)

    def test_async_callback_is_kept(self):
        async def cb() -> None:
            return None

        mixin = FailCallbackMixin(fail_cb=cb)
        assert mixin.fail_cb is not None
        assert inspect.iscoroutinefunction(mixin.fail_cb)

    @pytest.mark.asyncio
    async def test_sync_callback_runs(self):
        calls: list[int] = []

        def cb() -> None:
            calls.append(1)

        mixin = FailCallbackMixin(fail_cb=cb)
        mixin._fire_fail_cb()
        await _drain(mixin)
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_sync_callback_does_not_log_error(self, monkeypatch):
        """同步回调正常返回时不得留下 error 日志."""
        recorder = _RecordingLogger()
        monkeypatch.setattr(checkers_module, "logger", recorder)
        calls: list[int] = []

        def cb() -> None:
            calls.append(1)

        mixin = FailCallbackMixin(fail_cb=cb)
        mixin._fire_fail_cb()
        await _drain(mixin)

        assert calls == [1]
        assert recorder.errors == []

    @pytest.mark.asyncio
    async def test_async_callback_runs(self):
        calls: list[int] = []

        async def cb() -> None:
            calls.append(1)

        mixin = FailCallbackMixin(fail_cb=cb)
        mixin._fire_fail_cb()
        await _drain(mixin)
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_no_callback_is_fine(self):
        mixin = FailCallbackMixin()
        mixin._fire_fail_cb()
        await _drain(mixin)

    @pytest.mark.asyncio
    async def test_callback_error_is_logged_and_does_not_escape(self, monkeypatch):
        """回调自己抛异常时: 记录下来, 不影响检查流程."""
        recorder = _RecordingLogger()
        monkeypatch.setattr(checkers_module, "logger", recorder)
        calls: list[int] = []

        def cb() -> None:
            calls.append(1)
            raise RuntimeError("boom")

        mixin = FailCallbackMixin(fail_cb=cb)
        mixin._fire_fail_cb()
        await _drain(mixin)

        assert calls == [1]
        assert any("boom" in msg for msg in recorder.errors)


class TestCheckerClasses:
    """三个 checker 走的是同一套回调包装."""

    @pytest.mark.asyncio
    async def test_owner_checker_wraps_sync_callback(self, monkeypatch):
        """身份提取失败时触发失败回调, 且不留下 error 日志."""
        recorder = _RecordingLogger()
        monkeypatch.setattr(checkers_module, "logger", recorder)
        calls: list[int] = []
        checker = OwnerChecker(factory=MagicMock(), fail_cb=lambda: calls.append(1))

        assert await checker.check(MagicMock()) is False
        await _drain(checker)

        assert calls == [1]
        assert recorder.errors == []

    @pytest.mark.asyncio
    async def test_admin_checker_wraps_sync_callback(self, monkeypatch):
        recorder = _RecordingLogger()
        monkeypatch.setattr(checkers_module, "logger", recorder)
        calls: list[int] = []
        checker = AdminChecker(factory=MagicMock(), fail_cb=lambda: calls.append(1))

        assert await checker.check(MagicMock()) is False
        await _drain(checker)

        assert calls == [1]
        assert recorder.errors == []
