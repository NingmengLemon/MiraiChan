"""
测试 settings 模块.
"""

from pathlib import Path

import pytest
from lemony_checkers.models import Rule, RuleSet
from lemony_checkers.settings import (
    get_admins,
    get_checker_global_settings,
    get_checker_plugin_settings,
    get_owner,
    is_admin,
    is_owner,
    reload_global_settings,
    reload_plugin_settings,
)
from lemony_settings import init_global_settings


class TestGetCheckerGlobalSettings:
    """测试 get_checker_global_settings 函数."""

    def test_creates_default_config(self, tmp_path: Path) -> None:
        """测试创建默认配置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()

        assert settings.mode == "blacklist"
        assert settings.owner is None
        assert settings.admins == []

        # 检查配置文件是否创建
        config_file = config_dir / "lemony_checkers" / "global.toml"
        assert config_file.exists()

    def test_returns_same_instance(self, tmp_path: Path) -> None:
        """测试返回相同实例."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings1 = get_checker_global_settings()
        settings2 = get_checker_global_settings()

        assert settings1 is settings2


class TestGetCheckerPluginSettings:
    """测试 get_checker_plugin_settings 函数."""

    def test_creates_default_config(self, tmp_path: Path) -> None:
        """测试创建默认插件配置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_plugin_settings("test_plugin")

        assert settings.enabled is True
        assert settings.mode is None
        assert settings.commands == {}

        # 检查配置文件是否创建
        config_file = config_dir / "lemony_checkers" / "test_plugin.toml"
        assert config_file.exists()

    def test_caches_plugin_settings(self, tmp_path: Path) -> None:
        """测试插件配置缓存."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings1 = get_checker_plugin_settings("cached_plugin")
        settings2 = get_checker_plugin_settings("cached_plugin")

        assert settings1 is settings2


class TestIsOwner:
    """测试 is_owner 函数."""

    def test_is_owner_true(self, tmp_path: Path) -> None:
        """测试用户是 Owner."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 123456

        assert is_owner(123456) is True

    def test_is_owner_false(self, tmp_path: Path) -> None:
        """测试用户不是 Owner."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 123456

        assert is_owner(999999) is False

    def test_is_owner_none(self, tmp_path: Path) -> None:
        """测试 Owner 未设置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        assert is_owner(123456) is False


class TestIsAdmin:
    """测试 is_admin 函数."""

    def test_is_admin_true(self, tmp_path: Path) -> None:
        """测试用户是 Admin."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.admins = [111, 222, 333]

        assert is_admin(222) is True

    def test_is_admin_false(self, tmp_path: Path) -> None:
        """测试用户不是 Admin."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.admins = [111, 222, 333]

        assert is_admin(999) is False


class TestGetOwnerAndAdmins:
    """测试 get_owner 和 get_admins 函数."""

    def test_get_owner(self, tmp_path: Path) -> None:
        """测试获取 Owner."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 123456

        assert get_owner() == 123456

    def test_get_owner_none(self, tmp_path: Path) -> None:
        """测试 Owner 未设置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        assert get_owner() is None

    def test_get_admins(self, tmp_path: Path) -> None:
        """测试获取 Admins."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.admins = [111, 222]

        admins = get_admins()
        assert admins == [111, 222]

        # 确保返回的是副本
        admins.append(333)
        assert get_admins() == [111, 222]


class TestReload:
    """测试 reload 函数."""

    def test_reload_global_settings(self, tmp_path: Path) -> None:
        """测试重新加载全局配置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        # 首次加载
        settings = get_checker_global_settings()
        assert settings.owner is None

        # 调用 reload 函数
        reloaded = reload_global_settings()
        # reload 返回的值应该与原值相等
        assert reloaded.owner == settings.owner
        assert reloaded.mode == settings.mode

    def test_reload_plugin_settings(self, tmp_path: Path) -> None:
        """测试重新加载插件配置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        # 首次加载
        settings = get_checker_plugin_settings("reload_test")
        assert settings.enabled is True

        # 调用 reload 函数
        reloaded = reload_plugin_settings("reload_test")
        # reload 返回的值应该与原值相等
        assert reloaded.enabled == settings.enabled
        assert reloaded.mode == settings.mode
