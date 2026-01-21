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
    GlobalConfig,
    PluginConfig,
    Rule,
    RuleConfig,
    RuleSet,
)
from .settings import (
    CHECKER_IDENTIFIER,
    get_admins,
    get_checker_global_settings,
    get_checker_plugin_settings,
    get_owner,
    is_admin,
    is_owner,
    reload_global_settings,
    reload_plugin_settings,
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
    "RuleConfig",  # 别名
    "CheckerGlobalSettings",
    "CheckerPluginSettings",
    "GlobalConfig",  # 别名
    "PluginConfig",  # 别名
    # Settings
    "CHECKER_IDENTIFIER",
    "get_checker_global_settings",
    "get_checker_plugin_settings",
    "reload_global_settings",
    "reload_plugin_settings",
    "is_owner",
    "is_admin",
    "get_owner",
    "get_admins",
]
