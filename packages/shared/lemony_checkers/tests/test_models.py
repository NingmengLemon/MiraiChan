"""models.py 单元测试 —— UniqueUser 模型、Rule、旧配置迁移."""

from __future__ import annotations

import logging

import pytest
from lemony_checkers.adapters.ob11 import (
    OB11_PROTOCOL_ID,
    Ob11UniqueUser,
    Ob11UniqueUserDataclass,
)
from lemony_checkers.core import CheckResult, match_rules
from lemony_checkers.migration import (
    legacy_ob11_rule,
    legacy_ob11_user_config,
    migrate_global_config_data,
    migrate_legacy_rules,
    migrate_legacy_unique_user_list,
    migrate_plugin_config_data,
    normalize_rule_priority,
    read_legacy_rule_priority,
)
from lemony_checkers.models import (
    ANY_VALUE,
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
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
        # dataclasses.FrozenInstanceError 是 AttributeError 的子类
        with pytest.raises(AttributeError):
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
# 省略 group_id 的配置 (TOML 写不出 null)
# ============================================================


class TestOptionalGroupId:
    """group_id 可以省略: TOML 无法表示 null, 写入时会丢掉该字段."""

    def test_pydantic_default_is_none(self):
        u = Ob11UniqueUser(user_id=1001, protocol=OB11_PROTOCOL_ID)
        assert u.group_id is None
        assert u.model_dump()["group_id"] is None

    def test_dataclass_default_is_none(self):
        """省略 group_id 得到 None, 而不是 FieldInfo 之类的脏值."""
        u = Ob11UniqueUserDataclass.from_kwargs(user_id=1001, protocol=OB11_PROTOCOL_ID)
        assert u.group_id is None  # type: ignore
        assert u.to_dict() == {
            "protocol": OB11_PROTOCOL_ID,
            "user_id": 1001,
            "group_id": None,
        }

    def test_required_fields_stay_required(self):
        """没有默认值的字段仍然不可省略."""
        with pytest.raises(TypeError):
            Ob11UniqueUserDataclass.from_kwargs(protocol=OB11_PROTOCOL_ID)

    def test_toml_round_trip(self, tmp_path):
        """TOML 往返: 省略 group_id 的配置重新加载不得抛校验错误."""
        from lemony_settings.readwriter import TomlReadWriter

        settings = CheckerGlobalSettings(
            mode="blacklist",
            owner=[
                Ob11UniqueUser(user_id=1001, group_id=None, protocol=OB11_PROTOCOL_ID)
            ],
        )
        path = tmp_path / "global.toml"
        writer = TomlReadWriter()
        writer.write(path, settings)

        raw = path.read_text(encoding="utf-8")
        assert "group_id" not in raw  # toml 表示不了 null, 该字段被丢掉

        loaded = writer.read(path, CheckerGlobalSettings)
        assert len(loaded.owner) == 1
        assert loaded.owner[0].user_id == 1001  # type: ignore
        assert loaded.owner[0].group_id is None  # type: ignore


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

    def testlegacy_ob11_user_config(self):
        """legacy_ob11_user_config 将 int 转为 dict."""
        result = legacy_ob11_user_config(1001)
        assert result == {
            "protocol": OB11_PROTOCOL_ID,
            "user_id": 1001,
            "group_id": None,
        }

    def testlegacy_ob11_rule_all(self):
        """ids=None 时 constrains=None."""
        result = legacy_ob11_rule("allow", None)
        assert result["action"] == "allow"
        assert result["protocol"] == OB11_PROTOCOL_ID
        assert result["constrains"] is None

    def testlegacy_ob11_rule_with_ids(self):
        """ids 不为 None 时包装为 user_id constraint."""
        result = legacy_ob11_rule("deny", {"user_id": [1001, 1002]})
        assert result["constrains"] == {"user_id": [1001, 1002]}

    def test_migrate_legacy_rules_group_first(self):
        """rule_priority=group_first 时 group_rules 在前."""
        legacy = {
            "user_rules": [{"action": "allow", "ids": [1001]}],
            "group_rules": [{"action": "deny", "ids": None}],
        }
        result = migrate_legacy_rules(legacy, rule_priority="group_first")
        assert len(result) == 2
        # group_rules[0]: ids=None 是"所有群聊", 不是"所有人"
        assert result[0]["constrains"] == {"group_id": [ANY_VALUE]}
        assert result[1]["constrains"] == {"user_id": [1001]}  # user_rules[0]

    def test_migrate_legacy_rules_user_first(self):
        """rule_priority=user_first 时 user_rules 在前."""
        legacy = {
            "user_rules": [{"action": "allow", "ids": [1001]}],
            "group_rules": [{"action": "deny", "ids": None}],
        }
        result = migrate_legacy_rules(legacy, rule_priority="user_first")
        assert len(result) == 2
        assert result[0]["constrains"] == {"user_id": [1001]}  # user_rules[0]
        # group_rules[0]: ids=None 是"所有群聊", 不是"所有人"
        assert result[1]["constrains"] == {"group_id": [ANY_VALUE]}

    def test_migrate_legacy_rules_no_rules_key(self):
        """无 user_rules/group_rules 时原样返回."""
        value = {"mode": "blacklist"}
        result = migrate_legacy_rules(value)
        assert result == value

    def test_migrate_legacy_rules_non_dict(self):
        """非 dict 输入原样返回."""
        assert migrate_legacy_rules(None) is None
        assert migrate_legacy_rules("invalid") == "invalid"

    def testmigrate_legacy_unique_user_list_int(self):
        """单个 int → 包装为列表."""
        result = migrate_legacy_unique_user_list(1001)
        assert result == [legacy_ob11_user_config(1001)]

    def testmigrate_legacy_unique_user_list_list_of_ints(self):
        """int 列表 → 每个 int 转为 dict."""
        result = migrate_legacy_unique_user_list([1001, 1002])
        assert len(result) == 2
        assert result[0] == legacy_ob11_user_config(1001)
        assert result[1] == legacy_ob11_user_config(1002)

    def testmigrate_legacy_unique_user_list_mixed(self):
        """混合列表 (int + dict) → int 被转换, dict 保留."""
        existing_dict = {
            "user_id": 9999,
            "group_id": None,
            "protocol": OB11_PROTOCOL_ID,
        }
        result = migrate_legacy_unique_user_list([1001, existing_dict])
        assert len(result) == 2
        assert result[0] == legacy_ob11_user_config(1001)
        assert result[1] is existing_dict

    def testmigrate_legacy_unique_user_list_none(self):
        """None → 空列表."""
        assert migrate_legacy_unique_user_list(None) == []


# ============================================================
# CheckerGlobalSettings 旧配置迁移
# ============================================================


class TestCheckerGlobalSettingsMigration:
    """测试 CheckerGlobalSettings 的旧配置自动迁移."""

    def test_legacy_int_owner_converted_to_list(self):
        """旧格式 owner=int 经迁移函数转为新的 list[UniqueUserConfig]."""
        migrated, changed = migrate_global_config_data(
            {"mode": "blacklist", "owner": 1001}
        )
        assert changed is True
        settings = CheckerGlobalSettings.model_validate(migrated)
        assert len(settings.owner) == 1
        owner = settings.owner[0]
        assert isinstance(owner, Ob11UniqueUser)
        assert owner.user_id == 1001
        assert owner.group_id is None

    def test_legacy_int_admins_converted(self):
        """旧格式 admins=[int, int] 经迁移函数转换."""
        migrated, changed = migrate_global_config_data(
            {"mode": "blacklist", "admins": [1001, 1002]}
        )
        assert changed is True
        settings = CheckerGlobalSettings.model_validate(migrated)
        assert len(settings.admins) == 2
        assert settings.admins[0].user_id == 1001  # type: ignore
        assert settings.admins[1].user_id == 1002  # type: ignore

    def test_legacy_rules_migrated(self):
        """旧格式 rules={user_rules:..., group_rules:...} 经迁移函数转换."""
        migrated, changed = migrate_global_config_data(
            {
                "mode": "blacklist",
                "rules": {
                    "user_rules": [{"action": "allow", "ids": [1001]}],
                    "group_rules": [],
                },
            }
        )
        assert changed is True
        settings = CheckerGlobalSettings.model_validate(migrated)
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
        """插件旧格式 rules 经迁移函数转换."""
        migrated, changed = migrate_plugin_config_data(
            {
                "rules": {
                    "user_rules": [{"action": "deny", "ids": [1002]}],
                    "group_rules": [],
                },
            }
        )
        assert changed is True
        settings = CheckerPluginSettings.model_validate(migrated)
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


# ============================================================
# 旧 group_rules 的"所有群聊"语义
# ============================================================


class TestLegacyGroupRuleSemantics:
    """旧 group_rules 只在群聊中参与判断: ids=None 不得扩大到私聊."""

    @staticmethod
    def _rules(legacy: dict[str, object]) -> list[Rule]:
        migrated, _ = migrate_plugin_config_data({"rules": legacy})
        return [Rule.model_validate(item) for item in migrated["rules"]]

    def test_all_groups_rule_matches_group_chat(self, ob11_user_alice):
        rules = self._rules(
            {"user_rules": [], "group_rules": [{"action": "deny", "ids": None}]}
        )
        assert match_rules(rules, ob11_user_alice) is CheckResult.DENY

    def test_all_groups_rule_skips_private_chat(self, ob11_user_alice_private):
        """旧实现里私聊只查 user_rules, group_rules 完全不参与."""
        rules = self._rules(
            {"user_rules": [], "group_rules": [{"action": "deny", "ids": None}]}
        )
        assert match_rules(rules, ob11_user_alice_private) is CheckResult.DEFAULT

    def test_specific_group_rule_only_matches_that_group(self, ob11_user_alice):
        rules = self._rules(
            {"user_rules": [], "group_rules": [{"action": "deny", "ids": [5000]}]}
        )
        assert match_rules(rules, ob11_user_alice) is CheckResult.DENY
        other_group = Ob11UniqueUserDataclass.from_kwargs(
            user_id=1001, group_id=6000, protocol=OB11_PROTOCOL_ID
        )
        assert match_rules(rules, other_group) is CheckResult.DEFAULT

    def test_legacy_user_rule_still_covers_private_chat(self, ob11_user_alice_private):
        """user_rules 的 ids=None 在旧实现里也覆盖私聊, 迁移后保持无条件匹配."""
        rules = self._rules(
            {"user_rules": [{"action": "allow", "ids": None}], "group_rules": []}
        )
        assert rules[0].constrains is None
        assert match_rules(rules, ob11_user_alice_private) is CheckResult.ALLOW


# ============================================================
# 旧 rule_priority 迁移
# ============================================================


class TestLegacyRulePriority:
    """rule_priority 缺失 / 为 null / 非预期取值时的收敛."""

    @pytest.mark.parametrize(
        "value", [None, "None", "", "USER_FIRST", "unknown", 0, [], "group_firs"]
    )
    def test_unrecognized_values_fall_back_to_default(self, value):
        assert normalize_rule_priority(value) == "group_first"

    def test_known_values_kept(self):
        assert normalize_rule_priority("user_first") == "user_first"
        assert normalize_rule_priority("group_first") == "group_first"

    def test_default_can_be_overridden(self):
        assert normalize_rule_priority(None, default="user_first") == "user_first"

    def test_invalid_default_falls_back_to_group_first(self):
        assert normalize_rule_priority(None, default="bogus") == "group_first"

    def test_plugin_null_priority_inherits_global_user_first(self):
        """插件 rule_priority=null 表示继承全局, 迁移时按全局优先级排序."""
        migrated, _ = migrate_plugin_config_data(
            {
                "rule_priority": None,
                "rules": {
                    "user_rules": [{"action": "allow", "ids": [1001]}],
                    "group_rules": [{"action": "deny", "ids": [5000]}],
                },
            },
            default_rule_priority="user_first",
        )
        assert migrated["rules"][0]["constrains"] == {"user_id": [1001]}
        assert migrated["rules"][1]["constrains"] == {"group_id": [5000]}

    def test_plugin_own_priority_wins_over_global(self):
        migrated, _ = migrate_plugin_config_data(
            {
                "rule_priority": "group_first",
                "rules": {
                    "user_rules": [{"action": "allow", "ids": [1001]}],
                    "group_rules": [{"action": "deny", "ids": [5000]}],
                },
            },
            default_rule_priority="user_first",
        )
        assert migrated["rules"][0]["constrains"] == {"group_id": [5000]}

    def test_rule_priority_removed_after_migration(self):
        migrated, _ = migrate_plugin_config_data({"rule_priority": "user_first"})
        assert "rule_priority" not in migrated


class TestReadLegacyRulePriority:
    """迁移前需要从旧全局配置里读出优先级 (迁移会删掉该字段)."""

    def test_reads_value_from_file(self, tmp_path):
        path = tmp_path / "global.json"
        path.write_text('{"rule_priority": "user_first"}', encoding="utf-8")
        assert read_legacy_rule_priority(path, "json") == "user_first"

    def test_missing_file_uses_default(self, tmp_path):
        missing = tmp_path / "nope.json"
        assert read_legacy_rule_priority(missing, "json") == "group_first"
        assert (
            read_legacy_rule_priority(missing, "json", default="user_first")
            == "user_first"
        )

    def test_file_without_field_uses_default(self, tmp_path):
        path = tmp_path / "global.json"
        path.write_text('{"mode": "whitelist"}', encoding="utf-8")
        assert read_legacy_rule_priority(path, "json") == "group_first"

    def test_null_field_uses_default(self, tmp_path):
        path = tmp_path / "global.json"
        path.write_text('{"rule_priority": null}', encoding="utf-8")
        assert read_legacy_rule_priority(path, "json", default="user_first") == (
            "user_first"
        )

    def test_unparsable_file_uses_default_and_warns(self, tmp_path, caplog):
        path = tmp_path / "global.json"
        path.write_text("{ not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            assert read_legacy_rule_priority(path, "json") == "group_first"
        assert "Failed to read legacy rule priority" in caplog.text

    def test_already_migrated_file_falls_back_to_backup(self, tmp_path):
        """全局文件在之前的启动里已迁移 (字段被删), 插件配置首次迁移时要从 .bak 读."""
        path = tmp_path / "global.json"
        path.write_text('{"mode": "whitelist"}', encoding="utf-8")
        (tmp_path / "global.json.bak").write_text(
            '{"rule_priority": "user_first"}', encoding="utf-8"
        )
        assert read_legacy_rule_priority(path, "json") == "user_first"

    def test_field_in_current_file_wins_over_backup(self, tmp_path):
        path = tmp_path / "global.json"
        path.write_text('{"rule_priority": "group_first"}', encoding="utf-8")
        (tmp_path / "global.json.bak").write_text(
            '{"rule_priority": "user_first"}', encoding="utf-8"
        )
        assert read_legacy_rule_priority(path, "json") == "group_first"

    def test_backup_without_field_uses_default(self, tmp_path):
        path = tmp_path / "global.json"
        path.write_text("{}", encoding="utf-8")
        (tmp_path / "global.json.bak").write_text("{}", encoding="utf-8")
        assert (
            read_legacy_rule_priority(path, "json", default="user_first")
            == "user_first"
        )

    def test_unsupported_format_uses_default_and_warns(self, tmp_path, caplog):
        path = tmp_path / "global.conf"
        path.write_text("mode=whitelist", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            assert read_legacy_rule_priority(path, "ini") == "group_first"
        assert "Failed to read legacy rule priority" in caplog.text
