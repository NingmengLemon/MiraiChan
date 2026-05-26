"""lemony_checkers 测试共享 fixtures."""

from __future__ import annotations

from typing import Any

import pytest

# 触发 Ob11UniqueUser 的 __pydantic_on_complete__ 以注册到全局 registry
from lemony_checkers.adapters.ob11 import (  # noqa: F401
    OB11_PROTOCOL_ID,
    Ob11UniqueUser,
    Ob11UniqueUserDataclass,
)
from lemony_checkers.core import CheckResult
from lemony_checkers.models import (
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
    UniqueUserDataclassBase,
)

# ============================================================
# UniqueUser fixtures
# ============================================================


def _make_ob11_user(*, user_id: int, group_id: int | None) -> UniqueUserDataclassBase:
    """快捷构造 OB11 运行时用户."""
    return Ob11UniqueUserDataclass.from_kwargs(
        user_id=user_id,
        group_id=group_id,
        protocol=OB11_PROTOCOL_ID,
    )


@pytest.fixture
def ob11_user_alice() -> UniqueUserDataclassBase:
    """群聊用户 Alice (uid=1001, gid=5000)."""
    return _make_ob11_user(user_id=1001, group_id=5000)


@pytest.fixture
def ob11_user_bob() -> UniqueUserDataclassBase:
    """群聊用户 Bob (uid=1002, gid=5000)."""
    return _make_ob11_user(user_id=1002, group_id=5000)


@pytest.fixture
def ob11_user_alice_private() -> UniqueUserDataclassBase:
    """私聊用户 Alice (uid=1001, group_id=None)."""
    return _make_ob11_user(user_id=1001, group_id=None)


@pytest.fixture
def ob11_user_bob_private() -> UniqueUserDataclassBase:
    """私聊用户 Bob (uid=1002, group_id=None)."""
    return _make_ob11_user(user_id=1002, group_id=None)


@pytest.fixture
def ob11_owner_model() -> Ob11UniqueUser:
    """Owner 配置（仅 user_id=1，匹配所有群/私聊）."""
    return Ob11UniqueUser(user_id=1, group_id=None, protocol=OB11_PROTOCOL_ID)


@pytest.fixture
def ob11_admin_model() -> Ob11UniqueUser:
    """Admin 配置（user_id=1001, 不限群组）."""
    return Ob11UniqueUser(user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID)


# ============================================================
# Settings fixtures
# ============================================================


@pytest.fixture
def global_blacklist(ob11_owner_model: Ob11UniqueUser) -> CheckerGlobalSettings:
    """默认黑名单全局配置，含 1 个 owner."""
    return CheckerGlobalSettings(
        mode="blacklist",
        owner=[ob11_owner_model],
    )


@pytest.fixture
def global_whitelist(ob11_owner_model: Ob11UniqueUser) -> CheckerGlobalSettings:
    """默认白名单全局配置，含 1 个 owner."""
    return CheckerGlobalSettings(
        mode="whitelist",
        owner=[ob11_owner_model],
    )


@pytest.fixture
def plugin_settings_default() -> CheckerPluginSettings:
    """默认插件配置（enabled=True, mode=None 即继承全局）."""
    return CheckerPluginSettings()


@pytest.fixture
def plugin_disabled() -> CheckerPluginSettings:
    """被禁用的插件配置."""
    return CheckerPluginSettings(enabled=False)


@pytest.fixture
def plugin_whitelist() -> CheckerPluginSettings:
    """覆盖为白名单的插件配置."""
    return CheckerPluginSettings(mode="whitelist")


# ============================================================
# Rule fixtures
# ============================================================


def _ob11_rule(
    action: str, *, constrains: list[dict[str, list[Any]]] | None = None
) -> dict[str, Any]:
    """快捷构造 OB11 规则原始数据."""
    return {
        "action": action,
        "protocol": OB11_PROTOCOL_ID,
        "constrains": constrains,
    }


@pytest.fixture
def rule_allow_alice() -> Rule:
    """允许 Alice (uid=1001) 的规则."""
    return Rule(**_ob11_rule("allow", constrains=[{"user_id": [1001]}]))


@pytest.fixture
def rule_deny_bob() -> Rule:
    """拒绝 Bob (uid=1002) 的规则."""
    return Rule(**_ob11_rule("deny", constrains=[{"user_id": [1002]}]))


@pytest.fixture
def rule_allow_all() -> Rule:
    """无条件允许规则."""
    return Rule(**_ob11_rule("allow", constrains=None))


@pytest.fixture
def rule_deny_all() -> Rule:
    """无条件拒绝规则."""
    return Rule(**_ob11_rule("deny", constrains=None))
