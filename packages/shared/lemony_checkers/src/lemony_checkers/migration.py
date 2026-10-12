"""Legacy checker config migration helpers."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Literal

import json5
import tomli
import yaml
from lemony_settings.readwriter import get_readwriter
from lemony_settings.utils import ensure_config_path
from melobot.protocols.onebot.v11.const import (
    PROTOCOL_IDENTIFIER as OB11_PROTOCOL_IDENTIFIER,
)

from .models import ANY_VALUE, CheckerGlobalSettings, CheckerPluginSettings

logger = logging.getLogger(__name__)

#: 旧配置中 rule_priority 的合法取值
LEGACY_RULE_PRIORITIES: tuple[str, ...] = ("group_first", "user_first")

#: 旧全局配置中 rule_priority 的默认值
DEFAULT_LEGACY_RULE_PRIORITY = "group_first"


def normalize_rule_priority(
    value: Any, *, default: str = DEFAULT_LEGACY_RULE_PRIORITY
) -> str:
    """把旧配置里的 rule_priority 收敛为两个已知取值之一.

    旧插件配置中该字段可以是 null (表示继承全局配置), 也可能是缺失或非预期字符串.
    直接 ``str()`` 会把它变成 "None" 之类的值, 与 "user_first" 比较失败后落到
    group_first 分支, 规则顺序被静默改变.

    Args:
        value: 配置中的原始 rule_priority
        default: 无法识别时使用的优先级 (来自全局配置)

    Returns:
        "group_first" 或 "user_first"
    """
    if value in LEGACY_RULE_PRIORITIES:
        return value
    if default in LEGACY_RULE_PRIORITIES:
        return default
    return DEFAULT_LEGACY_RULE_PRIORITY


def legacy_ob11_user_config(user_id: int) -> dict[str, Any]:
    return {
        "protocol": OB11_PROTOCOL_IDENTIFIER,
        "user_id": user_id,
        "group_id": None,
    }


def legacy_ob11_rule(
    action: Any, constrains: dict[str, list[int]] | None
) -> dict[str, Any]:
    return {
        "action": action,
        "protocol": OB11_PROTOCOL_IDENTIFIER,
        "constrains": constrains,
    }


def migrate_legacy_rules(value: Any, *, rule_priority: str = "group_first") -> Any:
    if not isinstance(value, dict):
        return value
    if "user_rules" not in value and "group_rules" not in value:
        return value

    user_rules: list[dict[str, Any]] = []
    for raw_rule in value.get("user_rules") or []:
        if not isinstance(raw_rule, dict):
            user_rules.append(raw_rule)
            continue
        ids = raw_rule.get("ids")
        constrains = None if ids is None else {"user_id": ids}
        user_rules.append(legacy_ob11_rule(raw_rule.get("action"), constrains))

    group_rules: list[dict[str, Any]] = []
    for raw_rule in value.get("group_rules") or []:
        if not isinstance(raw_rule, dict):
            group_rules.append(raw_rule)
            continue
        ids = raw_rule.get("ids")
        if ids is None:
            # 旧语义: group_rules 按群号匹配, 且只在群聊中参与判断, ids=None 表示"所有群聊".
            # 写成 constrains=None 会让规则连私聊一起匹配 — 白名单模式下等于放宽了权限.
            constrains: dict[str, list[Any]] | None = {"group_id": [ANY_VALUE]}
        else:
            constrains = {"group_id": ids}
        group_rules.append(legacy_ob11_rule(raw_rule.get("action"), constrains))

    if rule_priority == "user_first":
        return [*user_rules, *group_rules]
    return [*group_rules, *user_rules]


def migrate_legacy_unique_user_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, int):
        return [legacy_ob11_user_config(value)]
    if isinstance(value, list):
        return [
            legacy_ob11_user_config(item) if isinstance(item, int) else item
            for item in value
        ]
    return value


def migrate_global_config_data(data: Any) -> tuple[Any, bool]:
    if not isinstance(data, dict):
        return data, False

    migrated = dict(data)
    changed = False

    if "owner" in migrated:
        owner = migrate_legacy_unique_user_list(migrated["owner"])
        if owner != migrated["owner"]:
            migrated["owner"] = owner
            changed = True

    if "admins" in migrated:
        admins = migrate_legacy_unique_user_list(migrated["admins"])
        if admins != migrated["admins"]:
            migrated["admins"] = admins
            changed = True

    if isinstance(migrated.get("rules"), dict) and (
        "user_rules" in migrated["rules"] or "group_rules" in migrated["rules"]
    ):
        migrated["rules"] = migrate_legacy_rules(
            migrated["rules"],
            rule_priority=normalize_rule_priority(migrated.get("rule_priority")),
        )
        changed = True

    if "rule_priority" in migrated:
        migrated.pop("rule_priority")
        changed = True

    return migrated, changed


def migrate_plugin_config_data(
    data: Any, *, default_rule_priority: str = DEFAULT_LEGACY_RULE_PRIORITY
) -> tuple[Any, bool]:
    if not isinstance(data, dict):
        return data, False

    migrated = dict(data)
    changed = False

    if isinstance(migrated.get("rules"), dict) and (
        "user_rules" in migrated["rules"] or "group_rules" in migrated["rules"]
    ):
        # 旧插件配置的 rule_priority 为 null 时继承全局配置的优先级, 因此需要调用方
        # 把全局值作为 default 传进来
        migrated["rules"] = migrate_legacy_rules(
            migrated["rules"],
            rule_priority=normalize_rule_priority(
                migrated.get("rule_priority"), default=default_rule_priority
            ),
        )
        changed = True

    if "rule_priority" in migrated:
        migrated.pop("rule_priority")
        changed = True

    return migrated, changed


def read_raw_config(path: Path, format: str) -> Any:
    match format:
        case "json":
            with path.open("r", encoding="utf-8") as f:
                return json5.load(f)
        case "yaml":
            with path.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        case "toml":
            with path.open("rb") as f:
                return tomli.load(f)
        case _:
            raise ValueError(f"Unsupported config format for migration: {format}")


def read_legacy_rule_priority(
    path: Path, format: str, *, default: str = DEFAULT_LEGACY_RULE_PRIORITY
) -> str:
    """读取旧配置文件里生效的规则优先级.

    必须在文件被迁移前调用: 迁移完成后 rule_priority 字段已被删除, 但插件配置里的
    rule_priority=null 仍然需要回退到全局配置的取值.

    Args:
        path: 配置文件路径
        format: 配置格式 (json/yaml/toml)
        default: 文件不存在或不可解析时使用的优先级

    Returns:
        "group_first" 或 "user_first"
    """
    if not path.exists():
        return normalize_rule_priority(None, default=default)
    try:
        raw = read_raw_config(path, format)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        # 读不出旧配置不应该阻断启动, 但要留下痕迹; 其他异常照常抛出
        logger.warning(
            f"Failed to read legacy rule priority from {str(path)!r}, "
            f"falling back to {default!r}: {exc}"
        )
        return normalize_rule_priority(None, default=default)
    if not isinstance(raw, dict):
        return normalize_rule_priority(None, default=default)
    return normalize_rule_priority(raw.get("rule_priority"), default=default)


def backup_config(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def migrate_config_file(
    path: Path,
    format: str,
    kind: Literal["global", "plugin"],
    *,
    default_rule_priority: str = DEFAULT_LEGACY_RULE_PRIORITY,
) -> bool:
    """Migrate a checker config file in place.

    Args:
        path: 配置文件路径
        format: 配置格式 (json/yaml/toml)
        kind: 全局配置还是插件配置
        default_rule_priority: kind="plugin" 且配置里 rule_priority 为 null 时继承的优先级

    Returns True when the file was migrated and rewritten.
    """
    if not path.exists():
        return False

    raw = read_raw_config(path, format)
    migrated, changed = (
        migrate_global_config_data(raw)
        if kind == "global"
        else migrate_plugin_config_data(
            raw, default_rule_priority=default_rule_priority
        )
    )
    if not changed:
        return False

    model = CheckerGlobalSettings if kind == "global" else CheckerPluginSettings
    validated = model.model_validate(migrated)
    ensure_config_path(path)
    backup_config(path)
    get_readwriter(format).write(path, validated)
    return True
