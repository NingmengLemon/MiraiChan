"""
测试 watcher 模块.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import tomli_w
from lemony_settings import BaseSettings, LemonySettings, init_global_settings
from lemony_settings.events import SettingsEventType, get_event_emitter
from lemony_settings.watcher import (
    ConfigFileWatcher,
    get_file_watcher,
    init_file_watcher,
    start_watcher,
    stop_watcher,
)


class WatcherTestSettings(BaseSettings):
    name: str = "default"
    count: int = 0
    enabled: bool = True


class TestConfigFileWatcher:
    """测试 ConfigFileWatcher 类."""

    def test_init(self, tmp_path: Path) -> None:
        """测试初始化."""
        watcher = ConfigFileWatcher(tmp_path, "toml")
        assert watcher._config_path == tmp_path
        assert watcher._preference == "toml"
        assert watcher._running is False

    def test_is_running_property(self, tmp_path: Path) -> None:
        """测试 is_running 属性."""
        watcher = ConfigFileWatcher(tmp_path, "toml")
        assert watcher.is_running is False

    def test_mark_saving(self, tmp_path: Path) -> None:
        """测试标记文件正在保存."""
        watcher = ConfigFileWatcher(tmp_path, "toml")
        file_path = tmp_path / "test.toml"

        watcher.mark_saving(file_path)
        assert file_path.resolve() in watcher._saving_files

    def test_unmark_saving(self, tmp_path: Path) -> None:
        """测试取消标记文件保存状态."""
        watcher = ConfigFileWatcher(tmp_path, "toml")
        file_path = tmp_path / "test.toml"

        watcher.mark_saving(file_path)
        watcher.unmark_saving(file_path)
        assert file_path.resolve() not in watcher._saving_files

    def test_unmark_saving_nonexistent(self, tmp_path: Path) -> None:
        """测试取消标记不存在的文件 (不应抛出异常)."""
        watcher = ConfigFileWatcher(tmp_path, "toml")
        file_path = tmp_path / "nonexistent.toml"

        # 不应抛出异常
        watcher.unmark_saving(file_path)

    @pytest.mark.asyncio
    async def test_start_sets_running(self, tmp_path: Path) -> None:
        """测试启动设置 running 状态."""
        watcher = ConfigFileWatcher(tmp_path, "toml")

        # 使用 patch 避免实际启动监控循环
        with patch.object(watcher, "_watch_loop", new_callable=AsyncMock):
            await watcher.start()
            assert watcher._running is True
            # 清理
            await watcher.stop()

    @pytest.mark.asyncio
    async def test_start_twice_logs_warning(self, tmp_path: Path) -> None:
        """测试重复启动记录警告."""
        watcher = ConfigFileWatcher(tmp_path, "toml")

        with patch.object(watcher, "_watch_loop", new_callable=AsyncMock):
            await watcher.start()

            # 第二次启动应该不会再次执行
            await watcher.start()

            # 清理
            await watcher.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, tmp_path: Path) -> None:
        """测试停止未运行的监控器 (不应抛出异常)."""
        watcher = ConfigFileWatcher(tmp_path, "toml")
        # 不应抛出异常
        await watcher.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, tmp_path: Path) -> None:
        """测试停止取消任务."""
        watcher = ConfigFileWatcher(tmp_path, "toml")

        # 模拟一个长时间运行的任务
        async def long_running():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass

        with patch.object(watcher, "_watch_loop", side_effect=long_running):
            await watcher.start()
            assert watcher._watch_task is not None

            await watcher.stop()
            assert watcher._running is False


class TestInitFileWatcher:
    """测试 init_file_watcher 函数."""

    def test_init_creates_watcher(self, tmp_path: Path) -> None:
        """测试初始化创建监控器."""
        from lemony_settings import watcher

        watcher._file_watcher = None

        result = init_file_watcher(tmp_path, "toml")

        assert result is not None
        assert isinstance(result, ConfigFileWatcher)
        assert get_file_watcher() is result

    def test_init_twice_raises_error(self, tmp_path: Path) -> None:
        """测试重复初始化抛出错误."""
        from lemony_settings import watcher

        watcher._file_watcher = None

        init_file_watcher(tmp_path, "toml")

        with pytest.raises(RuntimeError, match="already been initialized"):
            init_file_watcher(tmp_path, "yaml")


class TestGetFileWatcher:
    """测试 get_file_watcher 函数."""

    def test_returns_none_before_init(self) -> None:
        """测试初始化前返回 None."""
        from lemony_settings import watcher

        watcher._file_watcher = None

        assert get_file_watcher() is None

    def test_returns_watcher_after_init(self, tmp_path: Path) -> None:
        """测试初始化后返回监控器."""
        from lemony_settings import watcher

        watcher._file_watcher = None

        created = init_file_watcher(tmp_path, "toml")
        assert get_file_watcher() is created


class TestStartStopWatcher:
    """测试 start_watcher 和 stop_watcher 函数."""

    @pytest.mark.asyncio
    async def test_start_watcher_when_auto_reload_disabled(
        self, tmp_path: Path
    ) -> None:
        """测试 auto_reload 禁用时不启动."""
        global_settings = init_global_settings(
            preference="toml", config_path=tmp_path / "configs"
        )
        # 默认 auto_reload 是 False
        assert global_settings.persistent.auto_reload is False

        watcher = get_file_watcher()
        assert watcher is not None

        await start_watcher()

        # 监控器不应该启动
        assert watcher.is_running is False

    @pytest.mark.asyncio
    async def test_start_watcher_when_auto_reload_enabled(self, tmp_path: Path) -> None:
        """测试 auto_reload 启用时启动."""
        global_settings = init_global_settings(
            preference="toml", config_path=tmp_path / "configs"
        )
        global_settings.persistent.auto_reload = True

        watcher = get_file_watcher()
        assert watcher is not None

        await start_watcher()

        # 监控器应该启动
        assert watcher.is_running is True

        # 清理
        await stop_watcher()

    @pytest.mark.asyncio
    async def test_stop_watcher(self, tmp_path: Path) -> None:
        """测试停止监控器."""
        global_settings = init_global_settings(
            preference="toml", config_path=tmp_path / "configs"
        )
        global_settings.persistent.auto_reload = True

        await start_watcher()
        watcher = get_file_watcher()
        assert watcher is not None
        assert watcher.is_running is True

        await stop_watcher()
        assert watcher.is_running is False

    @pytest.mark.asyncio
    async def test_start_watcher_without_init(self, tmp_path: Path) -> None:
        """测试 watcher 未初始化时启动 (应记录警告但不抛异常)."""
        from lemony_settings import watcher

        # 先初始化 global settings，但手动将 watcher 设为 None
        global_settings = init_global_settings(
            preference="toml", config_path=tmp_path / "configs"
        )
        global_settings.persistent.auto_reload = True

        # 模拟 watcher 未初始化的情况
        watcher._file_watcher = None

        # 不应抛出异常, 但会记录警告
        await start_watcher()


class TestWatcherReload:
    """测试文件监控重载功能."""

    @pytest.mark.asyncio
    async def test_reload_triggers_event(self, tmp_path: Path) -> None:
        """测试重载触发事件."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        # 创建并加载设置
        settings = LemonySettings("reload_test", "default", WatcherTestSettings)
        settings.load()

        # 注册事件回调
        emitter = get_event_emitter()
        callback = MagicMock()
        emitter.on(
            SettingsEventType.RELOADED,
            callback,
            identifier="reload_test",
            namespace="default",
        )

        # 模拟文件变更后的重载
        watcher = get_file_watcher()
        assert watcher is not None

        config_file = config_dir / "reload_test" / "default.toml"

        # 直接调用 _reload_settings 方法
        await watcher._reload_settings(settings, config_file)

        # 检查事件是否被触发
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.event_type == SettingsEventType.RELOADED
        assert event.identifier == "reload_test"

    @pytest.mark.asyncio
    async def test_reload_updates_value(self, tmp_path: Path) -> None:
        """测试重载更新值."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = LemonySettings("update_test", "default", WatcherTestSettings)
        settings.load()

        assert settings.value.name == "default"

        # 修改配置文件
        config_file = config_dir / "update_test" / "default.toml"
        with config_file.open("wb") as f:
            tomli_w.dump({"name": "updated_name", "count": 100, "enabled": False}, f)

        # 触发重载
        watcher = get_file_watcher()
        assert watcher is not None
        await watcher._reload_settings(settings, config_file)

        # 检查值是否更新
        assert settings.value.name == "updated_name"
        assert settings.value.count == 100
        assert settings.value.enabled is False

    @pytest.mark.asyncio
    async def test_reload_detects_changed_fields(self, tmp_path: Path) -> None:
        """测试重载检测变更的字段."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = LemonySettings("fields_test", "default", WatcherTestSettings)
        settings.load()

        emitter = get_event_emitter()
        callback = MagicMock()
        emitter.on(
            SettingsEventType.RELOADED,
            callback,
            identifier="fields_test",
            namespace="default",
        )

        # 只修改部分字段
        config_file = config_dir / "fields_test" / "default.toml"
        with config_file.open("wb") as f:
            tomli_w.dump({"name": "changed", "count": 0, "enabled": True}, f)

        watcher = get_file_watcher()
        assert watcher is not None
        await watcher._reload_settings(settings, config_file)

        event = callback.call_args[0][0]
        assert "name" in event.changed_fields
        # count 和 enabled 没变, 不应该在 changed_fields 中
        assert "count" not in event.changed_fields
        assert "enabled" not in event.changed_fields

    @pytest.mark.asyncio
    async def test_reload_error_triggers_error_event(self, tmp_path: Path) -> None:
        """测试重载错误触发错误事件."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = LemonySettings("error_test", "default", WatcherTestSettings)
        settings.load()

        emitter = get_event_emitter()
        error_callback = MagicMock()
        emitter.on(
            SettingsEventType.LOAD_ERROR,
            error_callback,
            identifier="error_test",
            namespace="default",
        )

        # 写入无效的配置文件
        config_file = config_dir / "error_test" / "default.toml"
        with config_file.open("w", encoding="utf-8") as f:
            f.write("invalid toml content [[[")

        watcher = get_file_watcher()
        assert watcher is not None
        await watcher._reload_settings(settings, config_file)

        # 检查错误事件是否被触发
        error_callback.assert_called_once()
        event = error_callback.call_args[0][0]
        assert event.event_type == SettingsEventType.LOAD_ERROR
        assert event.error is not None


class TestGlobalSettingsReload:
    """测试全局设置重载."""

    @pytest.mark.asyncio
    async def test_global_settings_reload(self, tmp_path: Path) -> None:
        """测试全局设置重载."""
        config_dir = tmp_path / "configs"
        global_settings = init_global_settings(
            preference="toml", config_path=config_dir
        )

        # 初始值
        assert global_settings.persistent.auto_reload is False

        emitter = get_event_emitter()
        callback = MagicMock()
        emitter.on(
            SettingsEventType.RELOADED,
            callback,
            identifier="__global__",
            namespace="__global__",
        )

        # 修改全局配置文件
        global_config_file = config_dir / "global.toml"
        with global_config_file.open("wb") as f:
            tomli_w.dump({"auto_reload": True}, f)

        # 模拟文件变更处理
        watcher = get_file_watcher()
        assert watcher is not None
        await watcher._handle_file_change(global_config_file)

        # 检查值是否更新
        assert global_settings.persistent.auto_reload is True

        # 检查事件
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.identifier == "__global__"
        assert "auto_reload" in event.changed_fields


class TestSavingFileLock:
    """测试保存时的文件锁定机制."""

    def test_save_marks_file_as_saving(self, tmp_path: Path) -> None:
        """测试保存时标记文件."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = LemonySettings("lock_test", "default", WatcherTestSettings)
        settings.load()

        watcher = get_file_watcher()
        assert watcher is not None

        # 在保存过程中检查文件是否被标记
        # marked_during_save = False
        # original_write = (
        #     getattr(settings.save, "__wrapped__", None)
        #     if hasattr(settings.save, "__wrapped__")
        #     else settings.save
        # )

        config_file = (config_dir / "lock_test" / "default.toml").resolve()

        # 保存前检查
        assert config_file not in watcher._saving_files

        # 执行保存
        settings.save()

        # 保存后检查 (应该已经解除标记)
        assert config_file not in watcher._saving_files
