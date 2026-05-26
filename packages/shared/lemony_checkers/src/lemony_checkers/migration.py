"""Legacy checker config migration helpers."""

from __future__ import annotations

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

from .models import CheckerGlobalSettings, CheckerPluginSettings


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
        constrains = None if ids is None else {"group_id": ids}
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
            rule_priority=str(migrated.get("rule_priority", "group_first")),
        )
        changed = True

    if "rule_priority" in migrated:
        migrated.pop("rule_priority")
        changed = True

    return migrated, changed


def migrate_plugin_config_data(data: Any) -> tuple[Any, bool]:
    if not isinstance(data, dict):
        return data, False

    migrated = dict(data)
    changed = False

    if isinstance(migrated.get("rules"), dict) and (
        "user_rules" in migrated["rules"] or "group_rules" in migrated["rules"]
    ):
        migrated["rules"] = migrate_legacy_rules(
            migrated["rules"],
            rule_priority=str(migrated.get("rule_priority", "group_first")),
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


def backup_config(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def migrate_config_file(
    path: Path,
    format: str,
    kind: Literal["global", "plugin"],
) -> bool:
    """Migrate a checker config file in place.

    Returns True when the file was migrated and rewritten.
    """
    if not path.exists():
        return False

    raw = read_raw_config(path, format)
    migrated, changed = (
        migrate_global_config_data(raw)
        if kind == "global"
        else migrate_plugin_config_data(raw)
    )
    if not changed:
        return False

    model = CheckerGlobalSettings if kind == "global" else CheckerPluginSettings
    validated = model.model_validate(migrated)
    ensure_config_path(path)
    backup_config(path)
    get_readwriter(format).write(path, validated)
    return True
