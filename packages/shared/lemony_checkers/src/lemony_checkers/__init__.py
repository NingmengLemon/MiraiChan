"""
Lemony Checkers - 权限检查器库

一个基于配置的权限检查库, 专为 MiraiChan 设计.
使用 lemony_settings 进行配置管理, 支持全局规则和插件特定规则.

快速开始:
    >>> from lemony_checkers import LemonyChecker, OwnerChecker
    >>> from melobot.protocols.onebot.v11 import on_message
    >>>
    >>> # 使用插件级别的检查器
    >>> checker = LemonyChecker(plugin_name="my_plugin")
    >>>
    >>> @on_message(checker=checker)
    >>> async def handler():
    ...     pass
    >>>
    >>> # 使用 Owner 专用检查器
    >>> @on_message(checker=OwnerChecker())
    >>> async def owner_handler():
    ...     pass
"""

from . import checkers, models, settings
from .checkers import (
    AdminChecker,
    CheckResult,
    FailCallback,
    LemonyChecker,
    OwnerChecker,
)
from .models import (
    CheckerGlobalSettings,
    CheckerPluginSettings,
    Rule,
    RuleSet,
)
from .settings import (
    add_admin,
    add_global_rule,
    add_plugin_rule,
    clear_global_rules,
    clear_plugin_rules,
    # 获取配置
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
    # 保存配置
    save_global_settings,
    save_plugin_settings,
    set_command_enabled,
    set_global_mode,
    # 全局配置 API
    set_owner,
    # 插件配置 API
    set_plugin_enabled,
    set_plugin_mode,
)

__all__ = [
    # Modules
    "checkers",
    "models",
    "settings",
    # Checkers
    "LemonyChecker",
    "OwnerChecker",
    "AdminChecker",
    "CheckResult",
    "FailCallback",
    # Models
    "Rule",
    "RuleSet",
    "CheckerGlobalSettings",
    "CheckerPluginSettings",
    # Settings - 获取配置
    "get_checker_global_settings",
    "get_checker_plugin_settings",
    "reload_global_settings",
    "reload_plugin_settings",
    "is_owner",
    "is_admin",
    "get_owner",
    "get_admins",
    # Settings - 保存配置
    "save_global_settings",
    "save_plugin_settings",
    # Settings - 全局配置 API
    "set_owner",
    "add_admin",
    "remove_admin",
    "set_global_mode",
    "add_global_rule",
    "remove_global_rule",
    "clear_global_rules",
    # Settings - 插件配置 API
    "set_plugin_enabled",
    "set_plugin_mode",
    "set_command_enabled",
    "remove_command_setting",
    "add_plugin_rule",
    "remove_plugin_rule",
    "clear_plugin_rules",
]
