"""
测试 events 模块.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from lemony_settings.events import (
    SettingsChangeEvent,
    SettingsErrorEvent,
    SettingsEvent,
    SettingsEventEmitter,
    SettingsEventType,
    get_event_emitter,
    on_settings_event,
)


class TestSettingsEventType:
    def test_event_types_exist(self) -> None:
        """测试事件类型枚举存在."""
        assert SettingsEventType.BEFORE_CHANGE
        assert SettingsEventType.AFTER_CHANGE
        assert SettingsEventType.RELOADED
        assert SettingsEventType.SAVED
        assert SettingsEventType.LOAD_ERROR
        assert SettingsEventType.SAVE_ERROR


class TestSettingsEvent:
    def test_basic_event(self) -> None:
        """测试基本事件数据类."""
        event = SettingsEvent(
            event_type=SettingsEventType.SAVED,
            identifier="test_plugin",
            namespace="default",
            config_path=Path("/tmp/config.toml"),
        )

        assert event.event_type == SettingsEventType.SAVED
        assert event.identifier == "test_plugin"
        assert event.namespace == "default"
        assert event.config_path == Path("/tmp/config.toml")

    def test_change_event(self) -> None:
        """测试变更事件数据类."""
        event = SettingsChangeEvent(
            event_type=SettingsEventType.AFTER_CHANGE,
            identifier="plugin",
            namespace="ns",
            changed_fields=["field1", "field2"],
        )

        assert event.changed_fields == ["field1", "field2"]

    def test_error_event(self) -> None:
        """测试错误事件数据类."""
        error = ValueError("test error")
        event = SettingsErrorEvent(
            event_type=SettingsEventType.LOAD_ERROR,
            identifier="plugin",
            namespace="ns",
            error=error,
            error_message="test error",
        )

        assert event.error is error
        assert event.error_message == "test error"


class TestSettingsEventEmitter:
    def test_register_global_callback(self) -> None:
        """测试注册全局回调."""
        emitter = SettingsEventEmitter()
        callback = MagicMock()

        emitter.on(SettingsEventType.SAVED, callback)

        assert callback in emitter._global_callbacks[SettingsEventType.SAVED]

    def test_register_specific_callback(self) -> None:
        """测试注册特定配置的回调."""
        emitter = SettingsEventEmitter()
        callback = MagicMock()

        emitter.on(
            SettingsEventType.RELOADED,
            callback,
            identifier="my_plugin",
            namespace="config",
        )

        key = ("my_plugin", "config")
        assert key in emitter._specific_callbacks
        assert callback in emitter._specific_callbacks[key][SettingsEventType.RELOADED]

    def test_unregister_callback(self) -> None:
        """测试取消注册回调."""
        emitter = SettingsEventEmitter()
        callback = MagicMock()

        emitter.on(SettingsEventType.SAVED, callback)
        assert emitter.off(SettingsEventType.SAVED, callback) is True

        assert callback not in emitter._global_callbacks.get(
            SettingsEventType.SAVED, []
        )

    def test_unregister_nonexistent_callback(self) -> None:
        """测试取消注册不存在的回调."""
        emitter = SettingsEventEmitter()
        callback = MagicMock()

        assert emitter.off(SettingsEventType.SAVED, callback) is False

    @pytest.mark.asyncio
    async def test_emit_calls_global_callbacks(self) -> None:
        """测试触发事件调用全局回调."""
        emitter = SettingsEventEmitter()
        callback = MagicMock()

        emitter.on(SettingsEventType.SAVED, callback)

        event = SettingsEvent(
            event_type=SettingsEventType.SAVED,
            identifier="plugin",
            namespace="ns",
        )

        await emitter.emit(event)

        callback.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_emit_calls_specific_callbacks(self) -> None:
        """测试触发事件调用特定配置的回调."""
        emitter = SettingsEventEmitter()
        global_callback = MagicMock()
        specific_callback = MagicMock()

        emitter.on(SettingsEventType.SAVED, global_callback)
        emitter.on(
            SettingsEventType.SAVED,
            specific_callback,
            identifier="target_plugin",
            namespace="config",
        )

        # 触发目标配置的事件
        event = SettingsEvent(
            event_type=SettingsEventType.SAVED,
            identifier="target_plugin",
            namespace="config",
        )

        await emitter.emit(event)

        global_callback.assert_called_once()
        specific_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_does_not_call_other_specific_callbacks(self) -> None:
        """测试触发事件不调用其他配置的回调."""
        emitter = SettingsEventEmitter()
        other_callback = MagicMock()

        emitter.on(
            SettingsEventType.SAVED,
            other_callback,
            identifier="other_plugin",
            namespace="config",
        )

        event = SettingsEvent(
            event_type=SettingsEventType.SAVED,
            identifier="target_plugin",
            namespace="config",
        )

        await emitter.emit(event)

        other_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_emit_with_async_callback(self) -> None:
        """测试异步回调."""
        emitter = SettingsEventEmitter()
        async_callback = AsyncMock()

        emitter.on(SettingsEventType.SAVED, async_callback)

        event = SettingsEvent(
            event_type=SettingsEventType.SAVED,
            identifier="plugin",
            namespace="ns",
        )

        await emitter.emit(event)

        async_callback.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_emit_handles_callback_error(self) -> None:
        """测试回调错误处理."""
        emitter = SettingsEventEmitter()
        error_callback = MagicMock(side_effect=ValueError("callback error"))
        normal_callback = MagicMock()

        emitter.on(SettingsEventType.SAVED, error_callback)
        emitter.on(SettingsEventType.SAVED, normal_callback)

        event = SettingsEvent(
            event_type=SettingsEventType.SAVED,
            identifier="plugin",
            namespace="ns",
        )

        # 不应该抛出异常
        await emitter.emit(event)

        # 即使前一个回调出错, 后一个也应该被调用
        normal_callback.assert_called_once()


class TestOnSettingsEventDecorator:
    def test_decorator_registers_callback(self) -> None:
        """测试装饰器注册回调."""
        # 重置 emitter
        from lemony_settings import events

        events._event_emitter = None

        @on_settings_event(SettingsEventType.RELOADED)
        def my_callback(event: SettingsEvent) -> None:
            pass

        emitter = get_event_emitter()
        assert my_callback in emitter._global_callbacks[SettingsEventType.RELOADED]

    def test_decorator_with_identifier(self) -> None:
        """测试装饰器带标识符."""
        from lemony_settings import events

        events._event_emitter = None

        @on_settings_event(SettingsEventType.AFTER_CHANGE, identifier="specific_plugin")
        def my_specific_callback(event: SettingsEvent) -> None:
            pass

        emitter = get_event_emitter()
        key = ("specific_plugin", "default")
        assert (
            my_specific_callback
            in emitter._specific_callbacks[key][SettingsEventType.AFTER_CHANGE]
        )


class TestGetEventEmitter:
    def test_singleton(self) -> None:
        """测试事件发射器单例."""
        from lemony_settings import events

        events._event_emitter = None

        emitter1 = get_event_emitter()
        emitter2 = get_event_emitter()

        assert emitter1 is emitter2
