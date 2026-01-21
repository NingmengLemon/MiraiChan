"""
事件系统模块.

提供配置变更事件的定义和回调注册机制.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from melobot.log import get_logger
from pydantic import BaseModel

if TYPE_CHECKING:
    from .core import BaseSettings

logger = get_logger()


class SettingsEventType(Enum):
    """配置事件类型."""

    # 配置值即将被修改 (可用于验证或拦截)
    BEFORE_CHANGE = auto()
    # 配置值已被修改
    AFTER_CHANGE = auto()
    # 配置文件被重新加载
    RELOADED = auto()
    # 配置文件被保存
    SAVED = auto()
    # 配置文件加载失败
    LOAD_ERROR = auto()
    # 配置文件保存失败
    SAVE_ERROR = auto()


@dataclass
class SettingsEvent:
    """配置事件基类."""

    event_type: SettingsEventType
    identifier: str
    namespace: str
    # 事件相关的配置文件路径
    config_path: Path | None = None


@dataclass
class SettingsChangeEvent(SettingsEvent):
    """配置变更事件."""

    old_value: "BaseSettings | BaseModel | None" = None
    new_value: "BaseSettings | BaseModel | None" = None
    # 变更的字段名列表 (如果可以检测到)
    changed_fields: list[str] = field(default_factory=list)


@dataclass
class SettingsErrorEvent(SettingsEvent):
    """配置错误事件."""

    error: Exception | None = None
    error_message: str = ""


# 回调函数类型定义
# 同步回调
type SyncEventCallback = Callable[[SettingsEvent], None]
# 异步回调
type AsyncEventCallback = Callable[[SettingsEvent], Awaitable[None]]
# 通用回调 (可以是同步或异步)
type EventCallback = SyncEventCallback | AsyncEventCallback


class SettingsEventEmitter:
    """
    配置事件发射器.

    用于注册和触发配置变更事件的回调函数.
    支持同步和异步回调.
    """

    def __init__(self) -> None:
        # 全局回调 (所有配置的事件都会触发)
        self._global_callbacks: dict[SettingsEventType, list[EventCallback]] = {}
        # 特定配置的回调 (key: (identifier, namespace))
        self._specific_callbacks: dict[
            tuple[str, str], dict[SettingsEventType, list[EventCallback]]
        ] = {}

    def on(
        self,
        event_type: SettingsEventType,
        callback: EventCallback,
        *,
        identifier: str | None = None,
        namespace: str | None = None,
    ) -> EventCallback:
        """
        注册事件回调函数.

        Args:
            event_type: 要监听的事件类型
            callback: 回调函数 (可以是同步或异步)
            identifier: 可选, 只监听特定 identifier 的配置事件
            namespace: 可选, 只监听特定 namespace 的配置事件
                       (需要同时指定 identifier)

        Returns:
            返回传入的回调函数, 方便用作装饰器

        Example:
            >>> emitter = SettingsEventEmitter()
            >>> @emitter.on(SettingsEventType.AFTER_CHANGE)
            ... def on_change(event: SettingsEvent):
            ...     print(f"Config changed: {event.identifier}")
            ...
            >>> # 或者只监听特定配置
            >>> @emitter.on(SettingsEventType.RELOADED, identifier="my_plugin")
            ... async def on_reload(event: SettingsEvent):
            ...     print("my_plugin config reloaded")
        """
        if identifier is not None:
            # 注册特定配置的回调
            ns = namespace or "default"
            key = (identifier, ns)
            if key not in self._specific_callbacks:
                self._specific_callbacks[key] = {}
            if event_type not in self._specific_callbacks[key]:
                self._specific_callbacks[key][event_type] = []
            self._specific_callbacks[key][event_type].append(callback)
        else:
            # 注册全局回调
            if event_type not in self._global_callbacks:
                self._global_callbacks[event_type] = []
            self._global_callbacks[event_type].append(callback)

        return callback

    def off(
        self,
        event_type: SettingsEventType,
        callback: EventCallback,
        *,
        identifier: str | None = None,
        namespace: str | None = None,
    ) -> bool:
        """
        移除事件回调函数.

        Returns:
            如果成功移除返回 True, 否则返回 False
        """
        if identifier is not None:
            ns = namespace or "default"
            key = (identifier, ns)
            if key in self._specific_callbacks:
                callbacks = self._specific_callbacks[key].get(event_type, [])
                if callback in callbacks:
                    callbacks.remove(callback)
                    return True
        else:
            callbacks = self._global_callbacks.get(event_type, [])
            if callback in callbacks:
                callbacks.remove(callback)
                return True
        return False

    async def emit(self, event: SettingsEvent) -> None:
        """
        触发事件, 调用所有注册的回调函数.

        会先调用全局回调, 再调用特定配置的回调.
        """
        callbacks_to_call: list[EventCallback] = []

        # 收集全局回调
        callbacks_to_call.extend(self._global_callbacks.get(event.event_type, []))

        # 收集特定配置的回调
        key = (event.identifier, event.namespace)
        if key in self._specific_callbacks:
            callbacks_to_call.extend(
                self._specific_callbacks[key].get(event.event_type, [])
            )

        # 调用所有回调
        for callback in callbacks_to_call:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(
                    f"Error in event callback for {event.event_type.name}: {e}"
                )

    def emit_sync(self, event: SettingsEvent) -> None:
        """
        同步触发事件 (在事件循环中调度异步调用).

        适用于在同步代码中触发事件.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event))
        except RuntimeError:
            # 没有运行中的事件循环, 使用 asyncio.run
            # 但这会阻塞, 所以只调用同步回调
            self._emit_sync_only(event)

    def _emit_sync_only(self, event: SettingsEvent) -> None:
        """只调用同步回调."""
        callbacks_to_call: list[EventCallback] = []
        callbacks_to_call.extend(self._global_callbacks.get(event.event_type, []))

        key = (event.identifier, event.namespace)
        if key in self._specific_callbacks:
            callbacks_to_call.extend(
                self._specific_callbacks[key].get(event.event_type, [])
            )

        for callback in callbacks_to_call:
            try:
                result = callback(event)
                # 跳过异步回调
                if asyncio.iscoroutine(result):
                    result.close()  # 关闭未 await 的协程
                    logger.warning(
                        f"Async callback skipped in sync context for {event.event_type.name}"
                    )
            except Exception as e:
                logger.error(
                    f"Error in event callback for {event.event_type.name}: {e}"
                )


# 全局事件发射器实例
_event_emitter: SettingsEventEmitter | None = None


def get_event_emitter() -> SettingsEventEmitter:
    """获取全局事件发射器实例."""
    global _event_emitter
    if _event_emitter is None:
        _event_emitter = SettingsEventEmitter()
    return _event_emitter


def on_settings_event(
    event_type: SettingsEventType,
    *,
    identifier: str | None = None,
    namespace: str | None = None,
) -> Callable[[EventCallback], EventCallback]:
    """
    装饰器: 注册配置事件回调.

    Example:
        >>> @on_settings_event(SettingsEventType.AFTER_CHANGE)
        ... def handle_change(event: SettingsEvent):
        ...     print(f"Config {event.identifier} changed!")
        ...
        >>> @on_settings_event(SettingsEventType.RELOADED, identifier="my_plugin")
        ... async def handle_reload(event: SettingsEvent):
        ...     await do_something_async()
    """

    def decorator(callback: EventCallback) -> EventCallback:
        emitter = get_event_emitter()
        emitter.on(event_type, callback, identifier=identifier, namespace=namespace)
        return callback

    return decorator
