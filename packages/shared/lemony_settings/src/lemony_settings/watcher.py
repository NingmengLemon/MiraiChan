"""
文件监控模块.

使用 watchfiles 实现配置文件的自动重载功能.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from melobot.log import get_logger
from watchfiles import Change, awatch

if TYPE_CHECKING:
    from .core import LemonySettings

logger = get_logger()


class ConfigFileWatcher:
    """
    配置文件监控器.

    监控配置目录中的文件变化, 当检测到修改时触发重新加载.
    """

    def __init__(self, config_path: Path, preference: str) -> None:
        self._config_path = config_path
        self._preference = preference
        self._watch_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._running = False
        # 用于防止保存时触发重载的锁
        # key: 文件路径, value: 是否正在保存
        self._saving_files: set[Path] = set()

    @property
    def is_running(self) -> bool:
        return self._running

    def mark_saving(self, file_path: Path) -> None:
        """标记文件正在保存, 防止触发重载."""
        self._saving_files.add(file_path.resolve())

    def unmark_saving(self, file_path: Path) -> None:
        """取消标记文件保存状态."""
        self._saving_files.discard(file_path.resolve())

    async def start(self) -> None:
        """启动文件监控."""
        if self._running:
            logger.warning("ConfigFileWatcher is already running.")
            return

        self._running = True
        self._stop_event.clear()
        self._watch_task = asyncio.create_task(self._watch_loop())
        logger.info(f"ConfigFileWatcher started, watching: {self._config_path}")

    async def stop(self) -> None:
        """停止文件监控."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None

        logger.info("ConfigFileWatcher stopped.")

    async def _watch_loop(self) -> None:
        """文件监控主循环."""
        try:
            # watchfiles.awatch 是一个异步生成器
            async for changes in awatch(
                self._config_path,
                stop_event=self._stop_event,
                recursive=True,
            ):
                if not self._running:
                    break

                for change_type, change_path_str in changes:
                    change_path = Path(change_path_str)

                    # 只关注修改事件和我们关心的文件类型
                    if change_type != Change.modified:
                        continue
                    if change_path.suffix != f".{self._preference}":
                        continue

                    # 检查是否是我们自己在保存
                    if change_path.resolve() in self._saving_files:
                        logger.debug(
                            f"Ignoring change for {change_path} (self-triggered save)"
                        )
                        continue

                    logger.debug(f"Detected config file change: {change_path}")

                    # 尝试找到对应的 LemonySettings 实例
                    await self._handle_file_change(change_path)

        except asyncio.CancelledError:
            logger.debug("ConfigFileWatcher watch loop cancelled.")
        except Exception as e:
            logger.error(f"Error in ConfigFileWatcher: {e}")

    async def _handle_file_change(self, changed_file: Path) -> None:
        """处理文件变更."""
        from .core import (
            _SETTINGS_TABLE,
            PersistentGlobalSettings,
            get_global_settings,
            resolve_config_path,
        )
        from .events import (
            SettingsChangeEvent,
            SettingsErrorEvent,
            SettingsEventType,
            get_event_emitter,
        )
        from .readwriter import get_read_writer

        global_settings = get_global_settings()
        emitter = get_event_emitter()

        # 检查是否是全局配置文件
        global_config_path = resolve_config_path(
            global_settings.config_path,
            global_settings.preference,
            id_ns=None,
        )

        if changed_file.resolve() == global_config_path.resolve():
            # 重载全局配置 (只重载 filed 部分)
            try:
                readwriter = get_read_writer(global_settings.preference)
                new_filed = readwriter.read(changed_file, PersistentGlobalSettings)
                old_filed = global_settings.persistent

                # 检测变更的字段
                changed_fields = []
                for field_name in PersistentGlobalSettings.model_fields:
                    if getattr(new_filed, field_name) != getattr(old_filed, field_name):
                        changed_fields.append(field_name)

                if changed_fields:
                    # 更新 persistent (需要绕过 frozen)
                    object.__setattr__(global_settings, "persistent", new_filed)

                    event = SettingsChangeEvent(
                        event_type=SettingsEventType.RELOADED,
                        identifier="__global__",
                        namespace="__global__",
                        config_path=changed_file,
                        old_value=old_filed,
                        new_value=new_filed,
                        changed_fields=changed_fields,
                    )
                    await emitter.emit(event)
                    logger.info(
                        f"Global settings reloaded, changed fields: {changed_fields}"
                    )

            except Exception as e:
                event = SettingsErrorEvent(
                    event_type=SettingsEventType.LOAD_ERROR,
                    identifier="__global__",
                    namespace="__global__",
                    config_path=changed_file,
                    error=e,
                    error_message=str(e),
                )
                await emitter.emit(event)
                logger.error(f"Failed to reload global settings: {e}")
            return

        # 查找对应的 LemonySettings 实例
        for (identifier, namespace), settings in _SETTINGS_TABLE.items():
            expected_path = resolve_config_path(
                global_settings.config_path,
                global_settings.preference,
                id_ns=(identifier, namespace),
            )

            if changed_file.resolve() == expected_path.resolve():
                await self._reload_settings(settings, changed_file)
                break

    async def _reload_settings(
        self, settings: "LemonySettings", config_path: Path
    ) -> None:
        """重新加载指定的配置."""
        from .core import _Sentinel, get_global_settings
        from .events import (
            SettingsChangeEvent,
            SettingsErrorEvent,
            SettingsEventType,
            get_event_emitter,
        )

        global_settings = get_global_settings()
        emitter = get_event_emitter()

        try:
            old_value = (
                None if settings._value is _Sentinel.NOT_LOADED else settings._value
            )

            new_value = settings._load_from_file(
                config_path, global_settings.preference
            )

            # 检测变更的字段
            changed_fields = []
            if old_value is not None:
                for field_name in settings._model.model_fields:
                    old_field_value = getattr(old_value, field_name, None)
                    new_field_value = getattr(new_value, field_name, None)
                    if old_field_value != new_field_value:
                        changed_fields.append(field_name)

            # 更新值
            settings._value = new_value
            # 设置 settings 引用, 以便 auto_save 功能正常工作
            object.__setattr__(new_value, "_settings_ref", settings)

            event = SettingsChangeEvent(
                event_type=SettingsEventType.RELOADED,
                identifier=settings.identifier,
                namespace=settings.namespace,
                config_path=config_path,
                old_value=old_value,
                new_value=new_value,
                changed_fields=changed_fields,
            )
            await emitter.emit(event)
            logger.info(
                f"Settings '{settings.identifier}:{settings.namespace}' reloaded"
                + (f", changed fields: {changed_fields}" if changed_fields else "")
            )

        except Exception as e:
            event = SettingsErrorEvent(
                event_type=SettingsEventType.LOAD_ERROR,
                identifier=settings.identifier,
                namespace=settings.namespace,
                config_path=config_path,
                error=e,
                error_message=str(e),
            )
            await emitter.emit(event)
            logger.error(
                f"Failed to reload settings '{settings.identifier}:{settings.namespace}': {e}"
            )


# 全局文件监控器实例
_file_watcher: ConfigFileWatcher | None = None


def get_file_watcher() -> ConfigFileWatcher | None:
    """获取全局文件监控器实例 (可能为 None, 如果尚未初始化)."""
    return _file_watcher


def init_file_watcher(config_path: Path, preference: str) -> ConfigFileWatcher:
    """初始化全局文件监控器."""
    global _file_watcher
    if _file_watcher is not None:
        raise RuntimeError("ConfigFileWatcher has already been initialized.")
    _file_watcher = ConfigFileWatcher(config_path, preference)
    return _file_watcher


async def start_watcher() -> None:
    """启动文件监控器 (如果已初始化且 auto_reload 启用)."""
    from .core import get_global_settings

    global_settings = get_global_settings()
    if not global_settings.persistent.auto_reload:
        logger.debug("auto_reload is disabled, skipping watcher start.")
        return

    watcher = get_file_watcher()
    if watcher is None:
        logger.warning("File watcher not initialized, cannot start.")
        return

    await watcher.start()


async def stop_watcher() -> None:
    """停止文件监控器."""
    watcher = get_file_watcher()
    if watcher is not None:
        await watcher.stop()
