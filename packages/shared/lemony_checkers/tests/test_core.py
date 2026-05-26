"""core.py 单元测试 —— 框架无关的权限判定逻辑."""

from __future__ import annotations

import pytest

from lemony_checkers.adapters.ob11 import Ob11UniqueUser
from lemony_checkers.core import (
    CheckResult,
    check_command_permission,
    check_permission,
    check_rules,
    get_effective_mode,
    is_admin,
    is_owner,
    match_rules,
    matches_unique_user,
)
from lemony_checkers.models import (
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
    UniqueUserDataclassBase,
)


# ============================================================
# matches_unique_user
# ============================================================


class TestMatchesUniqueUser:
    """测试 matches_unique_user —— 配置用户与运行时用户匹配."""

    def test_exact_match(self, ob11_user_alice, ob11_admin_model):
        """配置 (user_id=1001, group_id=None) 匹配运行时 (1001, 5000)."""
        assert matches_unique_user(ob11_admin_model, ob11_user_alice) is True

    def test_exact_match_same_group(self, ob11_user_alice):
        """配置 (user_id=1001, group_id=5000) 匹配相同群的用户."""
        config = Ob11UniqueUser(
            user_id=1001, group_id=5000, protocol="OneBot-v11@Meloland"
        )
        assert matches_unique_user(config, ob11_user_alice) is True

    def test_group_mismatch(self, ob11_user_alice):
        """配置限定 group_id=9999 时不匹配 group_id=5000 的用户."""
        config = Ob11UniqueUser(
            user_id=1001, group_id=9999, protocol="OneBot-v11@Meloland"
        )
        assert matches_unique_user(config, ob11_user_alice) is False

    def test_user_id_mismatch(self, ob11_user_alice):
        """配置 user_id=9999 时不匹配 user_id=1001."""
        config = Ob11UniqueUser(
            user_id=9999, group_id=None, protocol="OneBot-v11@Meloland"
        )
        assert matches_unique_user(config, ob11_user_alice) is False

    def test_protocol_mismatch(self, ob11_user_alice):
        """协议不同时直接返回 False."""
        config = Ob11UniqueUser.model_construct(
            user_id=1001, group_id=None, protocol="tg@Somewhere"
        )
        assert matches_unique_user(config, ob11_user_alice) is False

    def test_wildcard_group_matches_private(self, ob11_user_alice_private):
        """group_id=None 的配置也匹配私聊用户 (group_id=None)."""
        config = Ob11UniqueUser(
            user_id=1001, group_id=None, protocol="OneBot-v11@Meloland"
        )
        assert matches_unique_user(config, ob11_user_alice_private) is True

    def test_no_identity_fields_warns_and_returns_false(self, ob11_user_alice, caplog):
        """配置仅含 protocol 无 identity 字段时返回 False 并警告."""
        config = Ob11UniqueUser.model_construct(
            user_id=None, group_id=None, protocol="OneBot-v11@Meloland"
        )
        with caplog.at_level("WARNING"):
            result = matches_unique_user(config, ob11_user_alice)
        assert result is False
        assert "without identity fields" in caplog.text.lower()


# ============================================================
# is_owner / is_admin
# ============================================================


class TestIsOwner:
    """测试 is_owner."""

    def test_owner_matches(self, global_blacklist, ob11_owner_model):
        """owner 用户被正确识别."""
        from lemony_checkers.adapters.ob11 import Ob11UniqueUserDataclass

        owner_user = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1, group_id=None, protocol="OneBot-v11@Meloland"
        )
        assert is_owner(global_blacklist, owner_user) is True

    def test_non_owner_does_not_match(self, global_blacklist, ob11_user_alice):
        """非 owner 用户不被误判."""
        assert is_owner(global_blacklist, ob11_user_alice) is False

    def test_empty_owner_list(self, ob11_user_alice):
        """无 owner 配置时所有人都不是 owner."""
        settings = CheckerGlobalSettings(mode="blacklist")
        assert is_owner(settings, ob11_user_alice) is False


class TestIsAdmin:
    """测试 is_admin."""

    def test_admin_matches(self, ob11_user_alice):
        """admin 用户被正确识别."""
        settings = CheckerGlobalSettings(
            mode="blacklist",
            admins=[
                Ob11UniqueUser(
                    user_id=1001, group_id=None, protocol="OneBot-v11@Meloland"
                )
            ],
        )
        assert is_admin(settings, ob11_user_alice) is True

    def test_non_admin_does_not_match(self, ob11_user_alice, ob11_user_bob):
        """非 admin 用户不被误判."""
        settings = CheckerGlobalSettings(
            mode="blacklist",
            admins=[
                Ob11UniqueUser(
                    user_id=1001, group_id=None, protocol="OneBot-v11@Meloland"
                )
            ],
        )
        assert is_admin(settings, ob11_user_bob) is False


# ============================================================
# match_rules
# ============================================================


class TestMatchRules:
    """测试 match_rules —— 规则匹配."""

    def test_empty_rules_returns_default(self, ob11_user_alice):
        """空规则列表返回 DEFAULT."""
        assert match_rules([], ob11_user_alice) is CheckResult.DEFAULT

    def test_allow_specific_user(
        self, ob11_user_alice, ob11_user_bob, rule_allow_alice
    ):
        """仅 Alice 匹配 allow 规则, Bob 不匹配."""
        assert match_rules([rule_allow_alice], ob11_user_alice) is CheckResult.ALLOW
        assert match_rules([rule_allow_alice], ob11_user_bob) is CheckResult.DEFAULT

    def test_deny_specific_user(self, ob11_user_alice, ob11_user_bob, rule_deny_bob):
        """仅 Bob 匹配 deny 规则."""
        assert match_rules([rule_deny_bob], ob11_user_bob) is CheckResult.DENY
        assert match_rules([rule_deny_bob], ob11_user_alice) is CheckResult.DEFAULT

    def test_first_match_wins(self, ob11_user_alice, rule_allow_alice, rule_deny_all):
        """规则按顺序匹配, 第一个匹配的生效."""
        # allow_alice 在前, 即使后面有 deny_all, Alice 依然通过
        result = match_rules([rule_allow_alice, rule_deny_all], ob11_user_alice)
        assert result is CheckResult.ALLOW

    def test_allow_all(self, ob11_user_alice, ob11_user_bob, rule_allow_all):
        """无条件允许规则匹配所有用户."""
        assert match_rules([rule_allow_all], ob11_user_alice) is CheckResult.ALLOW
        assert match_rules([rule_allow_all], ob11_user_bob) is CheckResult.ALLOW

    def test_deny_all(self, ob11_user_alice, ob11_user_bob, rule_deny_all):
        """无条件拒绝规则匹配所有用户."""
        assert match_rules([rule_deny_all], ob11_user_alice) is CheckResult.DENY
        assert match_rules([rule_deny_all], ob11_user_bob) is CheckResult.DENY

    def test_protocol_filtered(self, ob11_user_alice):
        """不同协议的规则被跳过."""
        rule = Rule(action="deny", protocol="tg@Somewhere", constrains=None)
        assert match_rules([rule], ob11_user_alice) is CheckResult.DEFAULT

    def test_or_constraints(self, ob11_user_alice, ob11_user_bob):
        """一个 rule 内多个 constraint 是 OR 关系."""
        rule = Rule(
            action="allow",
            protocol="OneBot-v11@Meloland",
            constrains=[{"user_id": [1001]}, {"user_id": [1002]}],
        )
        assert match_rules([rule], ob11_user_alice) is CheckResult.ALLOW
        assert match_rules([rule], ob11_user_bob) is CheckResult.ALLOW

    def test_and_fields_within_constraint(self, ob11_user_alice):
        """单个 constraint 内多字段是 AND 关系."""
        # Alice (1001, 5000) 匹配
        rule = Rule(
            action="allow",
            protocol="OneBot-v11@Meloland",
            constrains=[{"user_id": [1001], "group_id": [5000]}],
        )
        assert match_rules([rule], ob11_user_alice) is CheckResult.ALLOW

    def test_and_fields_mismatch(self, ob11_user_alice):
        """AND 条件中任一字段不匹配则整体不匹配."""
        rule = Rule(
            action="allow",
            protocol="OneBot-v11@Meloland",
            constrains=[{"user_id": [1001], "group_id": [9999]}],
        )
        assert match_rules([rule], ob11_user_alice) is CheckResult.DEFAULT


# ============================================================
# check_rules
# ============================================================


class TestCheckRules:
    """测试 check_rules —— 全局 + 插件规则组合."""

    def test_global_wins(self, global_blacklist, rule_allow_all):
        """全局规则先匹配, 插件规则不再检查."""
        global_blacklist.rules = [rule_allow_all]
        plugin = CheckerPluginSettings(
            rules=[Rule(action="deny", protocol="OneBot-v11@Meloland", constrains=None)]
        )
        result = check_rules(global_blacklist, plugin, _make_user(9999))
        assert result is CheckResult.ALLOW  # 全局 allow_all 命中

    def test_fallback_to_plugin(
        self, global_blacklist, ob11_user_alice, rule_allow_alice
    ):
        """全局无匹配时落入插件规则."""
        plugin = CheckerPluginSettings(rules=[rule_allow_alice])
        result = check_rules(global_blacklist, plugin, ob11_user_alice)
        assert result is CheckResult.ALLOW

    def test_no_plugin_settings(self, global_blacklist, ob11_user_alice):
        """plugin_settings 为 None 时只检查全局规则."""
        result = check_rules(global_blacklist, None, ob11_user_alice)
        assert result is CheckResult.DEFAULT


# ============================================================
# get_effective_mode
# ============================================================


class TestGetEffectiveMode:
    """测试 get_effective_mode."""

    def test_plugin_override(self, global_blacklist, plugin_whitelist):
        """插件设置了 mode 则优先使用."""
        assert get_effective_mode(global_blacklist, plugin_whitelist) == "whitelist"

    def test_fallback_to_global(self, global_blacklist, plugin_settings_default):
        """插件 mode 为 None 则使用全局 mode."""
        assert (
            get_effective_mode(global_blacklist, plugin_settings_default) == "blacklist"
        )

    def test_no_plugin_settings(self, global_blacklist):
        """无插件配置时使用全局 mode."""
        assert get_effective_mode(global_blacklist, None) == "blacklist"


# ============================================================
# check_permission
# ============================================================


class TestCheckPermission:
    """测试 check_permission —— 完整权限判定链路."""

    def test_owner_always_passes(self, global_blacklist):
        """Owner 无视所有规则直接通过."""
        from lemony_checkers.adapters.ob11 import Ob11UniqueUserDataclass

        owner = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1, group_id=None, protocol="OneBot-v11@Meloland"
        )
        assert (
            check_permission(
                global_settings=global_blacklist, plugin_settings=None, user=owner
            )
            is True
        )

    def test_plugin_disabled_denies(
        self, global_blacklist, plugin_disabled, ob11_user_alice
    ):
        """插件被禁用时非 owner 直接拒绝."""
        assert (
            check_permission(
                global_settings=global_blacklist,
                plugin_settings=plugin_disabled,
                user=ob11_user_alice,
            )
            is False
        )

    def test_admin_passes(self, ob11_user_alice):
        """Admin 用户通过检查."""
        settings = CheckerGlobalSettings(
            mode="blacklist",
            admins=[
                Ob11UniqueUser(
                    user_id=1001, group_id=None, protocol="OneBot-v11@Meloland"
                )
            ],
        )
        assert (
            check_permission(
                global_settings=settings, plugin_settings=None, user=ob11_user_alice
            )
            is True
        )

    def test_admin_check_disabled(self, ob11_user_alice):
        """allow_admin=False 时 admin 不自动通过."""
        settings = CheckerGlobalSettings(
            mode="whitelist",
            admins=[
                Ob11UniqueUser(
                    user_id=1001, group_id=None, protocol="OneBot-v11@Meloland"
                )
            ],
        )
        # whitelist 模式 + 无 allow 规则 → 默认拒绝
        assert (
            check_permission(
                global_settings=settings,
                plugin_settings=None,
                user=ob11_user_alice,
                allow_admin=False,
            )
            is False
        )

    def test_blacklist_default_allow(self, global_blacklist, ob11_user_alice):
        """黑名单模式下无匹配规则时默认允许."""
        assert (
            check_permission(
                global_settings=global_blacklist,
                plugin_settings=None,
                user=ob11_user_alice,
            )
            is True
        )

    def test_whitelist_default_deny(self, global_whitelist, ob11_user_alice):
        """白名单模式下无匹配规则时默认拒绝."""
        assert (
            check_permission(
                global_settings=global_whitelist,
                plugin_settings=None,
                user=ob11_user_alice,
            )
            is False
        )

    def test_rule_allows_in_whitelist(
        self, global_whitelist, ob11_user_alice, rule_allow_alice
    ):
        """白名单模式 + allow 规则 → 通过."""
        global_whitelist.rules = [rule_allow_alice]
        assert (
            check_permission(
                global_settings=global_whitelist,
                plugin_settings=None,
                user=ob11_user_alice,
            )
            is True
        )

    def test_rule_denies_in_blacklist(
        self, global_blacklist, ob11_user_alice, rule_deny_all
    ):
        """黑名单模式 + deny_all 规则 → 拒绝."""
        global_blacklist.rules = [rule_deny_all]
        assert (
            check_permission(
                global_settings=global_blacklist,
                plugin_settings=None,
                user=ob11_user_alice,
            )
            is False
        )


# ============================================================
# check_command_permission
# ============================================================


class TestCheckCommandPermission:
    """测试 check_command_permission —— 含命令启停的完整链路."""

    def test_disabled_command_denies(self, global_blacklist, ob11_user_alice):
        """命令被禁用时拒绝."""
        plugin = CheckerPluginSettings(commands={"secret_cmd": False})
        assert (
            check_command_permission(
                global_settings=global_blacklist,
                plugin_settings=plugin,
                user=ob11_user_alice,
                command_name="secret_cmd",
            )
            is False
        )

    def test_enabled_command_passes(self, global_blacklist, ob11_user_alice):
        """命令被显式启用时继续后续检查."""
        plugin = CheckerPluginSettings(commands={"normal_cmd": True})
        # 黑名单模式, 无 deny 规则 → 通过
        assert (
            check_command_permission(
                global_settings=global_blacklist,
                plugin_settings=plugin,
                user=ob11_user_alice,
                command_name="normal_cmd",
            )
            is True
        )

    def test_command_not_in_dict_defaults_enabled(
        self, global_blacklist, ob11_user_alice
    ):
        """未在 commands 字典中的命令默认启用."""
        plugin = CheckerPluginSettings(commands={})
        assert (
            check_command_permission(
                global_settings=global_blacklist,
                plugin_settings=plugin,
                user=ob11_user_alice,
                command_name="unknown_cmd",
            )
            is True
        )

    def test_no_command_name_skips_check(
        self, global_blacklist, ob11_user_alice, plugin_disabled
    ):
        """command_name 为 None 时不检查命令启停."""
        # 插件禁用 → 拒绝
        assert (
            check_command_permission(
                global_settings=global_blacklist,
                plugin_settings=plugin_disabled,
                user=ob11_user_alice,
                command_name=None,
            )
            is False
        )

    def test_owner_bypasses_disabled_command(self, global_blacklist):
        """Owner 无视命令禁用直接通过."""
        from lemony_checkers.adapters.ob11 import Ob11UniqueUserDataclass

        owner = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1, group_id=None, protocol="OneBot-v11@Meloland"
        )
        plugin = CheckerPluginSettings(commands={"disabled_cmd": False})
        assert (
            check_command_permission(
                global_settings=global_blacklist,
                plugin_settings=plugin,
                user=owner,
                command_name="disabled_cmd",
            )
            is True
        )


# ============================================================
# Helpers
# ============================================================


def _make_user(user_id: int, *, group_id: int | None = 5000) -> UniqueUserDataclassBase:
    """快捷创建测试用 OB11 用户."""
    from lemony_checkers.adapters.ob11 import Ob11UniqueUserDataclass

    return Ob11UniqueUserDataclass.from_kwargs(
        user_id=user_id,
        group_id=group_id,
        protocol="OneBot-v11@Meloland",
    )
