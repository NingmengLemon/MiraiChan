"""
配置管理模块.

使用 lemony_settings 进行配置的加载和管理.
"""

from lemony_settings import LemonySettings
from melobot.log import get_logger

from .models import CheckerGlobalSettings, CheckerPluginSettings

logger = get_logger()

# 模块标识符
CHECKER_IDENTIFIER = "lemony_checkers"

# 全局配置实例
_global_checker_settings: LemonySettings[CheckerGlobalSettings] | None = None

# 插件配置缓存
_plugin_settings_cache: dict[str, LemonySettings[CheckerPluginSettings]] = {}


def get_checker_global_settings() -> CheckerGlobalSettings:
    """
    获取权限检查器的全局配置.

    Returns:
        CheckerGlobalSettings: 全局配置实例

    Raises:
        RuntimeError: 如果配置尚未初始化
    """
    global _global_checker_settings

    if _global_checker_settings is None:
        _global_checker_settings = LemonySettings(
            identifier=CHECKER_IDENTIFIER,
            namespace="global",
            model=CheckerGlobalSettings,
        )
        _global_checker_settings.load()
        logger.info("Loaded checker global settings")

    return _global_checker_settings.value


def get_checker_plugin_settings(plugin_name: str) -> CheckerPluginSettings:
    """
    获取指定插件的权限配置.

    Args:
        plugin_name: 插件名称

    Returns:
        CheckerPluginSettings: 插件配置实例
    """
    if plugin_name not in _plugin_settings_cache:
        settings = LemonySettings(
            identifier=CHECKER_IDENTIFIER,
            namespace=plugin_name,
            model=CheckerPluginSettings,
        )
        settings.load()
        _plugin_settings_cache[plugin_name] = settings
        logger.info(f"Loaded checker settings for plugin: {plugin_name}")

    return _plugin_settings_cache[plugin_name].value


def reload_global_settings() -> CheckerGlobalSettings:
    """
    重新加载全局配置.

    Returns:
        CheckerGlobalSettings: 重新加载后的全局配置
    """
    global _global_checker_settings

    if _global_checker_settings is not None:
        _global_checker_settings.load()
        logger.info("Reloaded checker global settings")

    return get_checker_global_settings()


def reload_plugin_settings(plugin_name: str) -> CheckerPluginSettings:
    """
    重新加载指定插件的配置.

    Args:
        plugin_name: 插件名称

    Returns:
        CheckerPluginSettings: 重新加载后的插件配置
    """
    if plugin_name in _plugin_settings_cache:
        _plugin_settings_cache[plugin_name].load()
        logger.info(f"Reloaded checker settings for plugin: {plugin_name}")

    return get_checker_plugin_settings(plugin_name)


def is_owner(user_id: int) -> bool:
    """
    检查用户是否是机器人所有者.

    Args:
        user_id: 用户QQ号

    Returns:
        bool: 是否是所有者
    """
    global_settings = get_checker_global_settings()
    return global_settings.owner is not None and global_settings.owner == user_id


def is_admin(user_id: int) -> bool:
    """
    检查用户是否是机器人管理员.

    Args:
        user_id: 用户QQ号

    Returns:
        bool: 是否是管理员
    """
    global_settings = get_checker_global_settings()
    return user_id in global_settings.admins


def get_owner() -> int | None:
    """
    获取机器人所有者的QQ号.

    Returns:
        int | None: 所有者QQ号, 如果未设置则返回 None
    """
    return get_checker_global_settings().owner


def get_admins() -> list[int]:
    """
    获取机器人管理员列表.

    Returns:
        list[int]: 管理员QQ号列表
    """
    return get_checker_global_settings().admins.copy()
