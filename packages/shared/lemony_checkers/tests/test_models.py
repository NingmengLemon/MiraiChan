"""
测试 models 模块.
"""

import pytest
from lemony_checkers.models import (
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
    RuleSet,
)


class TestRule:
    """测试 Rule 模型."""

    def test_allow_rule(self) -> None:
        """测试允许规则."""
        rule = Rule(action="allow", ids=[123, 456])
        assert rule.action == "allow"
        assert rule.ids == [123, 456]

    def test_deny_rule(self) -> None:
        """测试拒绝规则."""
        rule = Rule(action="deny", ids=[789])
        assert rule.action == "deny"
        assert rule.ids == [789]

    def test_empty_ids(self) -> None:
        """测试空 ID 列表."""
        rule = Rule(action="allow")
        assert rule.ids is None

    def test_invalid_action(self) -> None:
        """测试无效动作."""
        with pytest.raises(ValueError):
            Rule(action="invalid")  # type: ignore


class TestRuleSet:
    """测试 RuleSet 模型."""

    def test_default(self) -> None:
        """测试默认值."""
        ruleset = RuleSet()
        assert ruleset.private == []
        assert ruleset.group == []

    def test_with_rules(self) -> None:
        """测试带规则的 RuleSet."""
        ruleset = RuleSet(
            private=[Rule(action="allow", ids=[111])],
            group=[Rule(action="deny", ids=[222])],
        )
        assert len(ruleset.private) == 1
        assert len(ruleset.group) == 1
        assert ruleset.private[0].action == "allow"
        assert ruleset.group[0].action == "deny"


class TestCheckerGlobalSettings:
    """测试 CheckerGlobalSettings 模型."""

    def test_defaults(self) -> None:
        """测试默认值."""
        settings = CheckerGlobalSettings()
        assert settings.mode == "blacklist"
        assert settings.owner is None
        assert settings.admins == []
        assert settings.rules.private == []
        assert settings.rules.group == []

    def test_custom_values(self) -> None:
        """测试自定义值."""
        settings = CheckerGlobalSettings(
            mode="whitelist",
            owner=123456,
            admins=[111, 222],
            rules=RuleSet(
                private=[Rule(action="allow", ids=[333])],
            ),
        )
        assert settings.mode == "whitelist"
        assert settings.owner == 123456
        assert settings.admins == [111, 222]
        assert len(settings.rules.private) == 1


class TestCheckerPluginSettings:
    """测试 CheckerPluginSettings 模型."""

    def test_defaults(self) -> None:
        """测试默认值."""
        settings = CheckerPluginSettings()
        assert settings.enabled is True
        assert settings.mode is None
        assert settings.rules.private == []
        assert settings.rules.group == []
        assert settings.commands == {}

    def test_custom_values(self) -> None:
        """测试自定义值."""
        settings = CheckerPluginSettings(
            enabled=False,
            mode="whitelist",
            rules=RuleSet(
                group=[Rule(action="deny", ids=[444])],
            ),
            commands={"echo": True, "secret": False},
        )
        assert settings.enabled is False
        assert settings.mode == "whitelist"
        assert len(settings.rules.group) == 1
        assert settings.commands["echo"] is True
        assert settings.commands["secret"] is False
