"""
测试 checkers 模块.
"""
# pyright: reportArgumentType=false

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# 导入 Mock 事件类
from conftest import MockGroupMessageEvent, MockMessageEvent
from lemony_checkers.checkers import (
    AdminChecker,
    CheckResult,
    LemonyChecker,
    OwnerChecker,
    _check_rules,
    _get_effective_mode,
    _match_rules,
)
from lemony_checkers.models import (
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
    RuleSet,
)
from lemony_checkers.settings import (
    get_checker_global_settings,
    get_checker_plugin_settings,
)
from lemony_settings import init_global_settings


class TestMatchRules:
    """测试 _match_rules 函数."""

    def test_match_allow(self) -> None:
        """测试匹配允许规则."""
        rules = [Rule(action="allow", ids=[123, 456])]
        result = _match_rules(rules, 123)
        assert result == CheckResult.ALLOW

    def test_match_deny(self) -> None:
        """测试匹配拒绝规则."""
        rules = [Rule(action="deny", ids=[123])]
        result = _match_rules(rules, 123)
        assert result == CheckResult.DENY

    def test_no_match(self) -> None:
        """测试无匹配规则."""
        rules = [Rule(action="allow", ids=[123])]
        result = _match_rules(rules, 999)
        assert result == CheckResult.DEFAULT

    def test_none_ids_matches_all(self) -> None:
        """测试 None ID 列表匹配所有."""
        rules = [Rule(action="deny", ids=None)]
        result = _match_rules(rules, 999)
        assert result == CheckResult.DENY

    def test_first_match_wins(self) -> None:
        """测试第一个匹配的规则生效."""
        rules = [
            Rule(action="deny", ids=[123]),
            Rule(action="allow", ids=[123]),  # 不会被执行
        ]
        result = _match_rules(rules, 123)
        assert result == CheckResult.DENY


class TestCheckRules:
    """测试 _check_rules 函数."""

    def test_global_private_rule(self) -> None:
        """测试全局私聊规则."""
        global_settings = CheckerGlobalSettings(
            rules=RuleSet(private=[Rule(action="deny", ids=[123])])
        )
        result = _check_rules(global_settings, None, user_id=123, group_id=None)
        assert result == CheckResult.DENY

    def test_global_group_rule(self) -> None:
        """测试全局群聊规则."""
        global_settings = CheckerGlobalSettings(
            rules=RuleSet(group=[Rule(action="allow", ids=[999])])
        )
        result = _check_rules(global_settings, None, user_id=123, group_id=999)
        assert result == CheckResult.ALLOW

    def test_plugin_rule_after_global(self) -> None:
        """测试插件规则在全局规则之后."""
        global_settings = CheckerGlobalSettings()  # 无规则
        plugin_settings = CheckerPluginSettings(
            rules=RuleSet(private=[Rule(action="deny", ids=[123])])
        )
        result = _check_rules(
            global_settings, plugin_settings, user_id=123, group_id=None
        )
        assert result == CheckResult.DENY

    def test_global_rule_priority(self) -> None:
        """测试全局规则优先于插件规则."""
        global_settings = CheckerGlobalSettings(
            rules=RuleSet(private=[Rule(action="allow", ids=[123])])
        )
        plugin_settings = CheckerPluginSettings(
            rules=RuleSet(private=[Rule(action="deny", ids=[123])])
        )
        # 全局规则先匹配
        result = _check_rules(
            global_settings, plugin_settings, user_id=123, group_id=None
        )
        assert result == CheckResult.ALLOW


class TestGetEffectiveMode:
    """测试 _get_effective_mode 函数."""

    def test_plugin_mode_priority(self) -> None:
        """测试插件模式优先."""
        global_settings = CheckerGlobalSettings(mode="blacklist")
        plugin_settings = CheckerPluginSettings(mode="whitelist")
        result = _get_effective_mode(global_settings, plugin_settings)
        assert result == "whitelist"

    def test_fallback_to_global(self) -> None:
        """测试回退到全局模式."""
        global_settings = CheckerGlobalSettings(mode="whitelist")
        plugin_settings = CheckerPluginSettings(mode=None)
        result = _get_effective_mode(global_settings, plugin_settings)
        assert result == "whitelist"

    def test_no_plugin_settings(self) -> None:
        """测试无插件配置."""
        global_settings = CheckerGlobalSettings(mode="blacklist")
        result = _get_effective_mode(global_settings, None)
        assert result == "blacklist"


class TestLemonyChecker:
    """测试 LemonyChecker 类."""

    @pytest.mark.asyncio
    async def test_owner_always_pass(self, tmp_path: Path) -> None:
        """测试 Owner 始终通过."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 12345

        checker = LemonyChecker()
        event = MockMessageEvent(user_id=12345)

        result = await checker.check(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_plugin_disabled(self, tmp_path: Path) -> None:
        """测试插件禁用时拒绝."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        plugin_settings = get_checker_plugin_settings("disabled_plugin")
        plugin_settings.enabled = False

        checker = LemonyChecker(plugin_name="disabled_plugin")
        event = MockMessageEvent(user_id=99999)

        result = await checker.check(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_command_disabled(self, tmp_path: Path) -> None:
        """测试命令禁用时拒绝."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        plugin_settings = get_checker_plugin_settings("cmd_plugin")
        plugin_settings.commands["secret"] = False

        checker = LemonyChecker(plugin_name="cmd_plugin", command_name="secret")
        event = MockMessageEvent(user_id=99999)

        result = await checker.check(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_pass(self, tmp_path: Path) -> None:
        """测试 Admin 通过检查."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.admins = [12345]

        checker = LemonyChecker(allow_admin=True)
        event = MockMessageEvent(user_id=12345)

        result = await checker.check(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_not_allowed(self, tmp_path: Path) -> None:
        """测试 Admin 不允许通过检查."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.admins = [12345]
        settings.mode = "whitelist"  # 默认拒绝

        checker = LemonyChecker(allow_admin=False)
        event = MockMessageEvent(user_id=12345)

        result = await checker.check(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_blacklist_default_allow(self, tmp_path: Path) -> None:
        """测试黑名单模式默认允许."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.mode = "blacklist"

        checker = LemonyChecker()
        event = MockMessageEvent(user_id=99999)

        result = await checker.check(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_whitelist_default_deny(self, tmp_path: Path) -> None:
        """测试白名单模式默认拒绝."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.mode = "whitelist"

        checker = LemonyChecker()
        event = MockMessageEvent(user_id=99999)

        result = await checker.check(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_fail_callback(self, tmp_path: Path) -> None:
        """测试失败回调."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.mode = "whitelist"

        callback = AsyncMock()
        checker = LemonyChecker(fail_cb=callback)
        event = MockMessageEvent(user_id=99999)

        await checker.check(event)
        callback.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_group_message(self, tmp_path: Path) -> None:
        """测试群消息检查."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.rules = RuleSet(group=[Rule(action="deny", ids=[98765])])

        checker = LemonyChecker()
        event = MockGroupMessageEvent(user_id=12345, group_id=98765)

        result = await checker.check(event)
        assert result is False


class TestOwnerChecker:
    """测试 OwnerChecker 类."""

    @pytest.mark.asyncio
    async def test_owner_pass(self, tmp_path: Path) -> None:
        """测试 Owner 通过."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 12345

        checker = OwnerChecker()
        event = MockMessageEvent(user_id=12345)

        result = await checker.check(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_non_owner_fail(self, tmp_path: Path) -> None:
        """测试非 Owner 拒绝."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 12345

        checker = OwnerChecker()
        event = MockMessageEvent(user_id=99999)

        result = await checker.check(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_fail_callback(self, tmp_path: Path) -> None:
        """测试失败回调."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 12345

        callback = AsyncMock()
        checker = OwnerChecker(fail_cb=callback)
        event = MockMessageEvent(user_id=99999)

        await checker.check(event)
        callback.assert_called_once_with(event)


class TestAdminChecker:
    """测试 AdminChecker 类."""

    @pytest.mark.asyncio
    async def test_owner_pass(self, tmp_path: Path) -> None:
        """测试 Owner 通过."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 12345

        checker = AdminChecker()
        event = MockMessageEvent(user_id=12345)

        result = await checker.check(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_pass(self, tmp_path: Path) -> None:
        """测试 Admin 通过."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.admins = [12345]

        checker = AdminChecker()
        event = MockMessageEvent(user_id=12345)

        result = await checker.check(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_non_admin_fail(self, tmp_path: Path) -> None:
        """测试非 Admin 拒绝."""
        config_dir = tmp_path / "configs"
        init_global_settings(preference="toml", config_path=config_dir)

        settings = get_checker_global_settings()
        settings.owner = 11111
        settings.admins = [22222]

        checker = AdminChecker()
        event = MockMessageEvent(user_id=99999)

        result = await checker.check(event)
        assert result is False
