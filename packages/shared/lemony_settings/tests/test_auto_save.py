"""
测试 auto_save 功能.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import tomli
from lemony_settings import BaseSettings, LemonySettings, init_global_settings


class AutoSaveTestSettings(BaseSettings):
    name: str = "default"
    count: int = 0


class TestAutoSave:
    def test_auto_save_on_field_change(self, tmp_path: Path) -> None:
        """测试字段修改时自动保存."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = LemonySettings("autosave_plugin", "default", AutoSaveTestSettings)
        settings.load()

        # 修改字段 - 应该触发自动保存
        settings.value.name = "auto_saved_name"

        # 检查文件是否已更新
        config_file = config_dir / "autosave_plugin" / "default.toml"
        with config_file.open("rb") as f:
            data = tomli.load(f)

        assert data["name"] == "auto_saved_name"

    def test_auto_save_multiple_changes(self, tmp_path: Path) -> None:
        """测试多次修改都会保存."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = LemonySettings("multi_change", "default", AutoSaveTestSettings)
        settings.load()

        settings.value.name = "first"
        settings.value.count = 100
        settings.value.name = "second"

        config_file = config_dir / "multi_change" / "default.toml"
        with config_file.open("rb") as f:
            data = tomli.load(f)

        assert data["name"] == "second"
        assert data["count"] == 100

    def test_auto_save_disabled(self, tmp_path: Path) -> None:
        """测试禁用 auto_save."""
        config_dir = tmp_path / "configs"
        global_settings = init_global_settings(
            preference="toml", config_path=config_dir
        )

        # 禁用 auto_save
        global_settings.filed.auto_save = False
        global_settings.save()

        settings = LemonySettings("no_autosave", "default", AutoSaveTestSettings)
        settings.load()

        original_count = settings.value.count
        settings.value.count = 9999

        # 文件不应该自动更新
        config_file = config_dir / "no_autosave" / "default.toml"
        with config_file.open("rb") as f:
            data = tomli.load(f)

        # 应该还是原来的值 (因为禁用了 auto_save)
        assert data["count"] == original_count

    def test_no_save_when_value_unchanged(self, tmp_path: Path) -> None:
        """测试值未改变时不保存."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = LemonySettings("no_change", "default", AutoSaveTestSettings)
        settings.load()

        # 记录保存次数
        save_count = 0
        original_save = settings.save

        def counting_save():
            nonlocal save_count
            save_count += 1
            original_save()

        settings.save = counting_save  # type: ignore

        # 设置相同的值
        settings.value.name = "default"  # 与默认值相同

        # 不应该触发保存
        assert save_count == 0

    def test_auto_save_triggers_event(self, tmp_path: Path) -> None:
        """测试 auto_save 触发事件."""
        from lemony_settings.events import SettingsEventType, get_event_emitter

        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        emitter = get_event_emitter()
        callback = MagicMock()
        emitter.on(SettingsEventType.AFTER_CHANGE, callback)

        settings = LemonySettings("event_test", "default", AutoSaveTestSettings)
        settings.load()

        settings.value.name = "changed"

        # 检查事件是否被触发
        callback.assert_called()
        event = callback.call_args[0][0]
        assert event.event_type == SettingsEventType.AFTER_CHANGE
        assert "name" in event.changed_fields
