"""
Framework-independent permission decision helpers.

This module intentionally does not import melobot. It evaluates configured
checker settings against a protocol-specific UniqueUser value; framework
adapters should only be responsible for extracting that UniqueUser from their
own event object and then calling these helpers.
"""

import logging
from enum import Enum, auto
from typing import Literal

from .models import (
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
    UniqueUserBase,
    UniqueUserDataclassBase,
)

logger = logging.getLogger(__name__)


class CheckResult(Enum):
    """Raw rule matching result."""

    ALLOW = auto()
    DENY = auto()
    DEFAULT = auto()


def matches_unique_user(
    configured_user: UniqueUserBase,
    incoming_user: UniqueUserDataclassBase,
) -> bool:
    """Return whether a configured identity matches a runtime identity.

    Fields set to None in configuration are treated as wildcards. For example,
    an OB11 admin configured with user_id only matches that user in private chat
    and in every group; adding group_id narrows it to that group.
    """
    incoming_dict = incoming_user.to_dict()
    if configured_user.protocol != incoming_dict.get("protocol"):
        return False

    configured_dict = configured_user.model_dump()
    match_fields = {
        key: value
        for key, value in configured_dict.items()
        if key != "protocol" and value is not None
    }
    if not match_fields:
        logger.warning(
            f"Ignoring unique user config without identity fields: {configured_dict!r}"
        )
        return False
    return all(incoming_dict.get(key) == value for key, value in match_fields.items())


def is_owner(
    global_settings: CheckerGlobalSettings,
    user: UniqueUserDataclassBase,
) -> bool:
    """Return whether the runtime identity is configured as an owner."""
    return any(matches_unique_user(owner, user) for owner in global_settings.owner)


def is_admin(
    global_settings: CheckerGlobalSettings,
    user: UniqueUserDataclassBase,
) -> bool:
    """Return whether the runtime identity is configured as an admin."""
    return any(matches_unique_user(admin, user) for admin in global_settings.admins)


def match_rules(rules: list[Rule], user: UniqueUserDataclassBase) -> CheckResult:
    """Match a runtime identity against ordered permission rules."""
    user_dict = user.to_dict()
    for rule in rules:
        if rule.protocol != user_dict.get("protocol"):
            continue

        if rule.constrains is None:
            return CheckResult.ALLOW if rule.action == "allow" else CheckResult.DENY

        # Multiple constraints are OR; fields inside one constraint are AND.
        for constraint in rule.constrains:
            if all(
                user_dict.get(field) in values for field, values in constraint.items()
            ):
                return CheckResult.ALLOW if rule.action == "allow" else CheckResult.DENY

    return CheckResult.DEFAULT


def check_rules(
    global_settings: CheckerGlobalSettings,
    plugin_settings: CheckerPluginSettings | None,
    user: UniqueUserDataclassBase,
) -> CheckResult:
    """Evaluate global rules first, then optional plugin rules."""
    result = match_rules(global_settings.rules, user)
    if result != CheckResult.DEFAULT:
        return result

    if plugin_settings is not None:
        result = match_rules(plugin_settings.rules, user)
        if result != CheckResult.DEFAULT:
            return result

    return CheckResult.DEFAULT


def get_effective_mode(
    global_settings: CheckerGlobalSettings,
    plugin_settings: CheckerPluginSettings | None,
) -> Literal["whitelist", "blacklist"]:
    """Return plugin mode if configured, otherwise global mode."""
    if plugin_settings is not None and plugin_settings.mode is not None:
        return plugin_settings.mode
    return global_settings.mode


def check_permission(
    *,
    global_settings: CheckerGlobalSettings,
    plugin_settings: CheckerPluginSettings | None,
    user: UniqueUserDataclassBase,
    allow_admin: bool = True,
) -> bool:
    """Return the final permission decision for a runtime identity."""
    if is_owner(global_settings, user):
        return True
    if plugin_settings is not None and not plugin_settings.enabled:
        return False
    if allow_admin and is_admin(global_settings, user):
        return True

    result = check_rules(global_settings, plugin_settings, user)
    if result is CheckResult.DEFAULT:
        mode = get_effective_mode(global_settings, plugin_settings)
        result = CheckResult.DENY if mode == "whitelist" else CheckResult.ALLOW
    return result is CheckResult.ALLOW


def check_command_permission(
    *,
    global_settings: CheckerGlobalSettings,
    plugin_settings: CheckerPluginSettings | None,
    user: UniqueUserDataclassBase,
    command_name: str | None = None,
    allow_admin: bool = True,
) -> bool:
    """Return permission decision including plugin command enable flags."""
    if is_owner(global_settings, user):
        return True
    if plugin_settings is not None:
        if not plugin_settings.enabled:
            return False
        if command_name is not None and not plugin_settings.commands.get(
            command_name, True
        ):
            return False
    if allow_admin and is_admin(global_settings, user):
        return True

    result = check_rules(global_settings, plugin_settings, user)
    if result is CheckResult.DEFAULT:
        mode = get_effective_mode(global_settings, plugin_settings)
        result = CheckResult.DENY if mode == "whitelist" else CheckResult.ALLOW
    return result is CheckResult.ALLOW
