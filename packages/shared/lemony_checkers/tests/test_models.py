"""models.py 单元测试 —— UniqueUser 模型、Rule、旧配置迁移."""

from __future__ import annotations

import pytest
from lemony_checkers.adapters.ob11 import (
    OB11_PROTOCOL_ID,
    Ob11UniqueUser,
    Ob11UniqueUserDataclass,
)
from lemony_checkers.models import (
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
    _legacy_ob11_rule,
    _legacy_ob11_user_config,
    _migrate_legacy_rules,
    _migrate_legacy_unique_user_list,
)
from pydantic import ValidationError

# ============================================================
# Ob11UniqueUser (pydantic model)
# ============================================================


class TestOb11UniqueUserPydantic:
    """测试 Ob11UniqueUser pydantic 模型."""

    def test_construction_valid(self):
        """正常构造."""
        u = Ob11UniqueUser(user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID)
        assert u.user_id == 1001
        assert u.group_id is None
        assert u.protocol == OB11_PROTOCOL_ID

    def test_with_group_id(self):
        """带 group_id 的构造."""
        u = Ob11UniqueUser(user_id=1001, group_id=5000, protocol=OB11_PROTOCOL_ID)
        assert u.group_id == 5000

    def test_missing_user_id_raises(self):
        """缺少 user_id 时抛出 ValidationError."""
        with pytest.raises(ValidationError):
            Ob11UniqueUser(group_id=None, protocol=OB11_PROTOCOL_ID)  # type: ignore[arg-type]

    def test_frozen_immutable(self):
        """frozen 模型不可修改."""
        u = Ob11UniqueUser(user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID)
        with pytest.raises(ValidationError):
            u.user_id = 9999  # type: ignore[misc]

    def test_model_dump(self):
        """model_dump 输出正确的字典."""
        u = Ob11UniqueUser(user_id=1001, group_id=5000, protocol=OB11_PROTOCOL_ID)
        d = u.model_dump()
        assert d == {"user_id": 1001, "group_id": 5000, "protocol": OB11_PROTOCOL_ID}

    def test_model_validate_from_dict(self):
        """从字典反序列化."""
        u = Ob11UniqueUser.model_validate(
            {"user_id": 1001, "group_id": None, "protocol": OB11_PROTOCOL_ID}
        )
        assert u.user_id == 1001

    def test_equality(self):
        """相同值的两个实例相等."""
        a = Ob11UniqueUser(user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID)
        b = Ob11UniqueUser(user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID)
        assert a == b

    def test_inequality(self):
        """不同值不相等."""
        a = Ob11UniqueUser(user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID)
        b = Ob11UniqueUser(user_id=1002, group_id=None, protocol=OB11_PROTOCOL_ID)
        assert a != b


# ============================================================
# Ob11UniqueUserDataclass (runtime dataclass)
# ============================================================


class TestOb11UniqueUserDataclass:
    """测试 Ob11UniqueUserDataclass 运行时 dataclass."""

    def test_from_kwargs_construction(self):
        """from_kwargs 构造."""
        u = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1001, group_id=5000, protocol=OB11_PROTOCOL_ID
        )
        assert u.user_id == 1001  # type: ignore
        assert u.group_id == 5000  # type: ignore
        assert u.protocol == OB11_PROTOCOL_ID  # type: ignore

    def test_frozen(self):
        """dataclass 是 frozen 的, 不可修改."""
        u = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID
        )
        with pytest.raises(Exception):  # FrozenInstanceError 或 AttributeError
            u.user_id = 9999  # type: ignore[misc]

    def test_to_dict(self):
        """to_dict 返回正确的字典."""
        u = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1001, group_id=5000, protocol=OB11_PROTOCOL_ID
        )
        d = u.to_dict()
        assert d == {"user_id": 1001, "group_id": 5000, "protocol": OB11_PROTOCOL_ID}

    def test_to_tuple(self):
        """to_tuple 返回按实际字段声明的元组 (protocol 继承自 UniqueUserBase, 排第一)."""
        u = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1001, group_id=5000, protocol=OB11_PROTOCOL_ID
        )
        t = u.to_tuple()
        # make_dataclass 按 model_fields.items() 顺序: protocol -> user_id -> group_id
        assert t == (OB11_PROTOCOL_ID, 1001, 5000)

    def test_get_pydantic_model(self):
        """get_pydantic_model 返回正确的 pydantic model 类."""
        model = Ob11UniqueUserDataclass.get_pydantic_model()
        assert model is Ob11UniqueUser

    def test_equality(self):
        """相同值的两个 dataclass 实例相等."""
        a = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID
        )
        b = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID
        )
        assert a == b
        assert hash(a) == hash(b)


# ============================================================
# Rule model
# ============================================================


class TestRule:
    """测试 Rule 模型."""

    def test_basic_rule(self):
        """基本规则构造."""
        r = Rule(action="allow", protocol=OB11_PROTOCOL_ID, constrains=None)
        assert r.action == "allow"
        assert r.constrains is None

    def test_rule_with_constraints(self):
        """带约束条件的规则."""
        r = Rule(
            action="deny",
            protocol=OB11_PROTOCOL_ID,
            constrains=[{"user_id": [1001, 1002]}],
        )
        assert r.constrains == [{"user_id": [1001, 1002]}]

    def test_migrate_single_constraint(self):
        """field_validator 将单个 dict 自动包装为 list."""
        r = Rule(
            action="allow",
            protocol=OB11_PROTOCOL_ID,
            constrains={"user_id": [1001]},  # type: ignore[arg-type]
        )
        assert r.constrains == [{"user_id": [1001]}]

    def test_migrate_single_constraint_none(self):
        """None 保持为 None."""
        r = Rule(action="allow", protocol=OB11_PROTOCOL_ID, constrains=None)
        assert r.constrains is None

    def test_missing_protocol_raises(self):
        """缺少 protocol 时抛出 ValidationError."""
        with pytest.raises(ValidationError):
            Rule(action="allow")  # type: ignore[call-arg]

    def test_invalid_action_raises(self):
        """无效 action 抛出 ValidationError."""
        with pytest.raises(ValidationError):
            Rule(action="invalid", protocol=OB11_PROTOCOL_ID)  # type: ignore[arg-type]


# ============================================================
# 旧配置迁移
# ============================================================


class TestLegacyMigrationFunctions:
    """测试旧配置迁移函数."""

    def test_legacy_ob11_user_config(self):
        """_legacy_ob11_user_config 将 int 转为 dict."""
        result = _legacy_ob11_user_config(1001)
        assert result == {
            "protocol": OB11_PROTOCOL_ID,
            "user_id": 1001,
            "group_id": None,
        }

    def test_legacy_ob11_rule_all(self):
        """ids=None 时 constrains=None."""
        result = _legacy_ob11_rule("allow", None)
        assert result["action"] == "allow"
        assert result["protocol"] == OB11_PROTOCOL_ID
        assert result["constrains"] is None

    def test_legacy_ob11_rule_with_ids(self):
        """ids 不为 None 时包装为 user_id constraint."""
        result = _legacy_ob11_rule("deny", {"user_id": [1001, 1002]})
        assert result["constrains"] == {"user_id": [1001, 1002]}

    def test_migrate_legacy_rules_group_first(self):
        """rule_priority=group_first 时 group_rules 在前, ids=None 时 constrains=None."""
        legacy = {
            "user_rules": [{"action": "allow", "ids": [1001]}],
            "group_rules": [{"action": "deny", "ids": None}],
        }
        result = _migrate_legacy_rules(legacy, rule_priority="group_first")
        assert len(result) == 2
        assert (
            result[0]["constrains"] is None
        )  # group_rules[0]: ids=None → constrains=None
        assert result[1]["constrains"] == {"user_id": [1001]}  # user_rules[0]

    def test_migrate_legacy_rules_user_first(self):
        """rule_priority=user_first 时 user_rules 在前."""
        legacy = {
            "user_rules": [{"action": "allow", "ids": [1001]}],
            "group_rules": [{"action": "deny", "ids": None}],
        }
        result = _migrate_legacy_rules(legacy, rule_priority="user_first")
        assert len(result) == 2
        assert result[0]["constrains"] == {"user_id": [1001]}  # user_rules[0]
        assert (
            result[1]["constrains"] is None
        )  # group_rules[0]: ids=None → constrains=None

    def test_migrate_legacy_rules_no_rules_key(self):
        """无 user_rules/group_rules 时原样返回."""
        value = {"mode": "blacklist"}
        result = _migrate_legacy_rules(value)
        assert result == value

    def test_migrate_legacy_rules_non_dict(self):
        """非 dict 输入原样返回."""
        assert _migrate_legacy_rules(None) is None
        assert _migrate_legacy_rules("invalid") == "invalid"

    def test_migrate_legacy_unique_user_list_int(self):
        """单个 int → 包装为列表."""
        result = _migrate_legacy_unique_user_list(1001)
        assert result == [_legacy_ob11_user_config(1001)]

    def test_migrate_legacy_unique_user_list_list_of_ints(self):
        """int 列表 → 每个 int 转为 dict."""
        result = _migrate_legacy_unique_user_list([1001, 1002])
        assert len(result) == 2
        assert result[0] == _legacy_ob11_user_config(1001)
        assert result[1] == _legacy_ob11_user_config(1002)

    def test_migrate_legacy_unique_user_list_mixed(self):
        """混合列表 (int + dict) → int 被转换, dict 保留."""
        existing_dict = {
            "user_id": 9999,
            "group_id": None,
            "protocol": OB11_PROTOCOL_ID,
        }
        result = _migrate_legacy_unique_user_list([1001, existing_dict])
        assert len(result) == 2
        assert result[0] == _legacy_ob11_user_config(1001)
        assert result[1] is existing_dict

    def test_migrate_legacy_unique_user_list_none(self):
        """None → 空列表."""
        assert _migrate_legacy_unique_user_list(None) == []


# ============================================================
# CheckerGlobalSettings 旧配置迁移
# ============================================================


class TestCheckerGlobalSettingsMigration:
    """测试 CheckerGlobalSettings 的旧配置自动迁移."""

    def test_legacy_int_owner_converted_to_list(self):
        """旧格式 owner=int 自动转为新的 list[UniqueUserConfig]."""
        settings = CheckerGlobalSettings.model_validate(
            {"mode": "blacklist", "owner": 1001}
        )
        assert len(settings.owner) == 1
        owner = settings.owner[0]
        assert isinstance(owner, Ob11UniqueUser)
        assert owner.user_id == 1001
        assert owner.group_id is None

    def test_legacy_int_admins_converted(self):
        """旧格式 admins=[int, int] 自动转换."""
        settings = CheckerGlobalSettings.model_validate(
            {"mode": "blacklist", "admins": [1001, 1002]}
        )
        assert len(settings.admins) == 2
        assert settings.admins[0].user_id == 1001  # type: ignore
        assert settings.admins[1].user_id == 1002  # type: ignore

    def test_legacy_rules_migrated(self):
        """旧格式 rules={user_rules:..., group_rules:...} 自动迁移."""
        settings = CheckerGlobalSettings.model_validate(
            {
                "mode": "blacklist",
                "rules": {
                    "user_rules": [{"action": "allow", "ids": [1001]}],
                    "group_rules": [],
                },
            }
        )
        assert len(settings.rules) == 1
        assert settings.rules[0].action == "allow"
        assert settings.rules[0].constrains == [{"user_id": [1001]}]

    def test_new_format_preserved(self):
        """新格式直接使用, 不经迁移."""
        settings = CheckerGlobalSettings.model_validate(
            {
                "mode": "whitelist",
                "owner": [
                    {"user_id": 1, "group_id": None, "protocol": OB11_PROTOCOL_ID}
                ],
                "rules": [
                    {
                        "action": "allow",
                        "protocol": OB11_PROTOCOL_ID,
                        "constrains": [{"user_id": [1001], "group_id": [5000]}],
                    }
                ],
            }
        )
        assert settings.mode == "whitelist"
        assert settings.owner[0].user_id == 1  # type: ignore
        assert settings.rules[0].constrains == [{"user_id": [1001], "group_id": [5000]}]

    def test_default_owner_is_empty_list(self):
        """默认 owner 为空列表."""
        settings = CheckerGlobalSettings()
        assert settings.owner == []

    def test_default_admins_is_empty_list(self):
        """默认 admins 为空列表."""
        settings = CheckerGlobalSettings()
        assert settings.admins == []


# ============================================================
# CheckerPluginSettings 旧配置迁移
# ============================================================


class TestCheckerPluginSettingsMigration:
    """测试 CheckerPluginSettings 的旧配置迁移."""

    def test_legacy_rules_migrated(self):
        """插件旧格式 rules 自动迁移."""
        settings = CheckerPluginSettings.model_validate(
            {
                "rules": {
                    "user_rules": [{"action": "deny", "ids": [1002]}],
                    "group_rules": [],
                },
            }
        )
        assert len(settings.rules) == 1
        assert settings.rules[0].action == "deny"
        assert settings.rules[0].constrains == [{"user_id": [1002]}]

    def test_defaults(self):
        """默认值."""
        settings = CheckerPluginSettings()
        assert settings.enabled is True
        assert settings.mode is None
        assert settings.rules == []
        assert settings.commands == {}
