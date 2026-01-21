"""
测试 settings 模块.
"""

from pathlib import Path

from lemony_checkers.settings import (
    add_admin,
    add_global_rule,
    add_plugin_rule,
    clear_global_rules,
    clear_plugin_rules,
    get_admins,
    get_checker_global_settings,
    get_checker_plugin_settings,
    get_owner,
    is_admin,
    is_owner,
    reload_global_settings,
    reload_plugin_settings,
    remove_admin,
    remove_command_setting,
    remove_global_rule,
    remove_plugin_rule,
    set_command_enabled,
    set_global_mode,
    # 编程式 API
    set_owner,
    set_plugin_enabled,
    set_plugin_mode,
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


# ============================================================================
# 编程式 API 测试
# ============================================================================


class TestSetOwner:
    """测试 set_owner 函数."""

    def test_set_owner(self, tmp_path: Path) -> None:
        """测试设置 Owner."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        set_owner(123456)
        assert get_owner() == 123456

    def test_clear_owner(self, tmp_path: Path) -> None:
        """测试清除 Owner."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        set_owner(123456)
        assert get_owner() == 123456

        set_owner(None)
        assert get_owner() is None


class TestAdminManagement:
    """测试管理员管理函数."""

    def test_add_admin(self, tmp_path: Path) -> None:
        """测试添加管理员."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        result = add_admin(111)
        assert result is True
        assert 111 in get_admins()

    def test_add_duplicate_admin(self, tmp_path: Path) -> None:
        """测试添加重复管理员."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        add_admin(111)
        result = add_admin(111)
        assert result is False
        assert get_admins().count(111) == 1

    def test_remove_admin(self, tmp_path: Path) -> None:
        """测试移除管理员."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        add_admin(111)
        result = remove_admin(111)
        assert result is True
        assert 111 not in get_admins()

    def test_remove_nonexistent_admin(self, tmp_path: Path) -> None:
        """测试移除不存在的管理员."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        result = remove_admin(999)
        assert result is False


class TestGlobalMode:
    """测试全局模式设置."""

    def test_set_global_mode(self, tmp_path: Path) -> None:
        """测试设置全局模式."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        set_global_mode("whitelist")
        assert get_checker_global_settings().mode == "whitelist"

        set_global_mode("blacklist")
        assert get_checker_global_settings().mode == "blacklist"


class TestGlobalRules:
    """测试全局规则管理."""

    def test_add_global_rule(self, tmp_path: Path) -> None:
        """测试添加全局规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        rule = add_global_rule("user", "deny", [123])
        assert rule.action == "deny"
        assert rule.ids == [123]

        settings = get_checker_global_settings()
        assert len(settings.rules.user_rules) == 1
        assert settings.rules.user_rules[0].action == "deny"

    def test_add_global_rule_match_all(self, tmp_path: Path) -> None:
        """测试添加匹配所有的规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        rule = add_global_rule("group", "allow", None)
        assert rule.ids is None

    def test_remove_global_rule(self, tmp_path: Path) -> None:
        """测试移除全局规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        add_global_rule("user", "deny", [123])
        add_global_rule("user", "allow", [456])

        removed = remove_global_rule("user", 0)
        assert removed is not None
        assert removed.ids == [123]

        settings = get_checker_global_settings()
        assert len(settings.rules.user_rules) == 1
        assert settings.rules.user_rules[0].ids == [456]

    def test_remove_invalid_index(self, tmp_path: Path) -> None:
        """测试移除无效索引."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        removed = remove_global_rule("user", 99)
        assert removed is None

    def test_clear_global_rules(self, tmp_path: Path) -> None:
        """测试清除全局规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        add_global_rule("user", "deny", [123])
        add_global_rule("group", "allow", [456])

        count = clear_global_rules()
        assert count == 2

        settings = get_checker_global_settings()
        assert len(settings.rules.user_rules) == 0
        assert len(settings.rules.group_rules) == 0

    def test_clear_specific_rule_type(self, tmp_path: Path) -> None:
        """测试清除特定类型规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        add_global_rule("user", "deny", [123])
        add_global_rule("group", "allow", [456])

        count = clear_global_rules("user")
        assert count == 1

        settings = get_checker_global_settings()
        assert len(settings.rules.user_rules) == 0
        assert len(settings.rules.group_rules) == 1


class TestPluginSettings:
    """测试插件配置管理."""

    def test_set_plugin_enabled(self, tmp_path: Path) -> None:
        """测试设置插件启用状态."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        set_plugin_enabled("test_plugin", False)
        assert get_checker_plugin_settings("test_plugin").enabled is False

        set_plugin_enabled("test_plugin", True)
        assert get_checker_plugin_settings("test_plugin").enabled is True

    def test_set_plugin_mode(self, tmp_path: Path) -> None:
        """测试设置插件模式."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        set_plugin_mode("test_plugin", "whitelist")
        assert get_checker_plugin_settings("test_plugin").mode == "whitelist"

        set_plugin_mode("test_plugin", None)
        assert get_checker_plugin_settings("test_plugin").mode is None


class TestCommandSettings:
    """测试命令设置管理."""

    def test_set_command_enabled(self, tmp_path: Path) -> None:
        """测试设置命令启用状态."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        set_command_enabled("test_plugin", "cmd1", False)
        settings = get_checker_plugin_settings("test_plugin")
        assert settings.commands.get("cmd1") is False

    def test_remove_command_setting(self, tmp_path: Path) -> None:
        """测试移除命令设置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        set_command_enabled("test_plugin", "cmd1", False)
        result = remove_command_setting("test_plugin", "cmd1")
        assert result is True

        settings = get_checker_plugin_settings("test_plugin")
        assert "cmd1" not in settings.commands

    def test_remove_nonexistent_command_setting(self, tmp_path: Path) -> None:
        """测试移除不存在的命令设置."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        # 先确保插件配置存在
        get_checker_plugin_settings("test_plugin")
        result = remove_command_setting("test_plugin", "nonexistent")
        assert result is False


class TestPluginRules:
    """测试插件规则管理."""

    def test_add_plugin_rule(self, tmp_path: Path) -> None:
        """测试添加插件规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        rule = add_plugin_rule("test_plugin", "user", "allow", [123])
        assert rule.action == "allow"

        settings = get_checker_plugin_settings("test_plugin")
        assert len(settings.rules.user_rules) == 1

    def test_remove_plugin_rule(self, tmp_path: Path) -> None:
        """测试移除插件规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        add_plugin_rule("test_plugin", "group", "deny", [456])
        removed = remove_plugin_rule("test_plugin", "group", 0)
        assert removed is not None

        settings = get_checker_plugin_settings("test_plugin")
        assert len(settings.rules.group_rules) == 0

    def test_clear_plugin_rules(self, tmp_path: Path) -> None:
        """测试清除插件规则."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        add_plugin_rule("test_plugin", "user", "allow", [111])
        add_plugin_rule("test_plugin", "group", "deny", [222])

        count = clear_plugin_rules("test_plugin")
        assert count == 2

        settings = get_checker_plugin_settings("test_plugin")
        assert len(settings.rules.user_rules) == 0
        assert len(settings.rules.group_rules) == 0
