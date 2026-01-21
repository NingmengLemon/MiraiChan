"""
配置管理模块.

使用 lemony_settings 进行配置的加载和管理.
"""

from typing import Literal

from lemony_settings import LemonySettings
from melobot.log import get_logger

from .models import CheckerGlobalSettings, CheckerPluginSettings, Rule

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


# ============================================================================
# 编程式 API - 用于动态修改配置
# ============================================================================


def set_owner(user_id: int | None) -> None:
    """
    设置机器人所有者.

    Args:
        user_id: 用户QQ号, 设为 None 可清除所有者
    """
    get_checker_global_settings().owner = user_id
    logger.info(f"Owner set to: {user_id}")


def add_admin(user_id: int) -> bool:
    """
    添加管理员.

    Args:
        user_id: 用户QQ号

    Returns:
        bool: 是否成功添加 (如果已存在则返回 False)
    """
    settings = get_checker_global_settings()
    if user_id in settings.admins:
        return False
    settings.admins = [*settings.admins, user_id]
    logger.info(f"Admin added: {user_id}")
    return True


def remove_admin(user_id: int) -> bool:
    """
    移除管理员.

    Args:
        user_id: 用户QQ号

    Returns:
        bool: 是否成功移除 (如果不存在则返回 False)
    """
    settings = get_checker_global_settings()
    if user_id not in settings.admins:
        return False
    settings.admins = [uid for uid in settings.admins if uid != user_id]
    logger.info(f"Admin removed: {user_id}")
    return True


def set_global_mode(mode: Literal["whitelist", "blacklist"]) -> None:
    """
    设置全局权限模式.

    Args:
        mode: 权限模式 ("whitelist" 或 "blacklist")
    """
    get_checker_global_settings().mode = mode
    logger.info(f"Global mode set to: {mode}")


def add_global_rule(
    rule_type: Literal["private", "group"],
    action: Literal["allow", "deny"],
    ids: list[int] | None = None,
) -> Rule:
    """
    添加全局规则.

    Args:
        rule_type: 规则类型 ("private" 私聊规则, "group" 群聊规则)
        action: 动作 ("allow" 允许, "deny" 拒绝)
        ids: ID列表 (用户ID或群组ID), None 表示匹配所有

    Returns:
        Rule: 添加的规则对象
    """
    settings = get_checker_global_settings()
    rule = Rule(action=action, ids=ids)

    if rule_type == "private":
        settings.rules.private = [*settings.rules.private, rule]
    else:
        settings.rules.group = [*settings.rules.group, rule]

    logger.info(f"Global {rule_type} rule added: action={action}, ids={ids}")
    return rule


def remove_global_rule(
    rule_type: Literal["private", "group"],
    index: int,
) -> Rule | None:
    """
    移除指定索引的全局规则.

    Args:
        rule_type: 规则类型 ("private" 或 "group")
        index: 规则索引

    Returns:
        Rule | None: 被移除的规则, 如果索引无效则返回 None
    """
    settings = get_checker_global_settings()
    rules = settings.rules.private if rule_type == "private" else settings.rules.group

    if index < 0 or index >= len(rules):
        return None

    removed = rules[index]
    new_rules = [r for i, r in enumerate(rules) if i != index]

    if rule_type == "private":
        settings.rules.private = new_rules
    else:
        settings.rules.group = new_rules

    logger.info(f"Global {rule_type} rule removed at index {index}")
    return removed


def clear_global_rules(rule_type: Literal["private", "group"] | None = None) -> int:
    """
    清除全局规则.

    Args:
        rule_type: 规则类型, None 表示清除所有规则

    Returns:
        int: 被清除的规则数量
    """
    settings = get_checker_global_settings()
    count = 0

    if rule_type is None or rule_type == "private":
        count += len(settings.rules.private)
        settings.rules.private = []

    if rule_type is None or rule_type == "group":
        count += len(settings.rules.group)
        settings.rules.group = []

    logger.info(
        f"Cleared {count} global rules"
        + (f" (type={rule_type})" if rule_type else " (all)")
    )
    return count


# ============================================================================
# 插件配置 API
# ============================================================================


def set_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    """
    设置插件是否启用.

    Args:
        plugin_name: 插件名称
        enabled: 是否启用
    """
    get_checker_plugin_settings(plugin_name).enabled = enabled
    logger.info(f"Plugin '{plugin_name}' enabled set to: {enabled}")


def set_plugin_mode(
    plugin_name: str, mode: Literal["whitelist", "blacklist"] | None
) -> None:
    """
    设置插件权限模式.

    Args:
        plugin_name: 插件名称
        mode: 权限模式, None 表示使用全局模式
    """
    get_checker_plugin_settings(plugin_name).mode = mode
    logger.info(f"Plugin '{plugin_name}' mode set to: {mode}")


def set_command_enabled(plugin_name: str, command_name: str, enabled: bool) -> None:
    """
    设置命令是否启用.

    Args:
        plugin_name: 插件名称
        command_name: 命令名称
        enabled: 是否启用
    """
    settings = get_checker_plugin_settings(plugin_name)
    # 使用新 dict 触发 auto_save
    settings.commands = {**settings.commands, command_name: enabled}
    logger.info(
        f"Command '{command_name}' in plugin '{plugin_name}' enabled set to: {enabled}"
    )


def remove_command_setting(plugin_name: str, command_name: str) -> bool:
    """
    移除命令的启用设置 (恢复为默认启用).

    Args:
        plugin_name: 插件名称
        command_name: 命令名称

    Returns:
        bool: 是否成功移除 (如果不存在则返回 False)
    """
    settings = get_checker_plugin_settings(plugin_name)
    if command_name not in settings.commands:
        return False
    settings.commands = {
        k: v for k, v in settings.commands.items() if k != command_name
    }
    logger.info(f"Command '{command_name}' setting removed from plugin '{plugin_name}'")
    return True


def add_plugin_rule(
    plugin_name: str,
    rule_type: Literal["private", "group"],
    action: Literal["allow", "deny"],
    ids: list[int] | None = None,
) -> Rule:
    """
    添加插件规则.

    Args:
        plugin_name: 插件名称
        rule_type: 规则类型 ("private" 私聊规则, "group" 群聊规则)
        action: 动作 ("allow" 允许, "deny" 拒绝)
        ids: ID列表 (用户ID或群组ID), None 表示匹配所有

    Returns:
        Rule: 添加的规则对象
    """
    settings = get_checker_plugin_settings(plugin_name)
    rule = Rule(action=action, ids=ids)

    if rule_type == "private":
        settings.rules.private = [*settings.rules.private, rule]
    else:
        settings.rules.group = [*settings.rules.group, rule]

    logger.info(
        f"Plugin '{plugin_name}' {rule_type} rule added: action={action}, ids={ids}"
    )
    return rule


def remove_plugin_rule(
    plugin_name: str,
    rule_type: Literal["private", "group"],
    index: int,
) -> Rule | None:
    """
    移除指定索引的插件规则.

    Args:
        plugin_name: 插件名称
        rule_type: 规则类型 ("private" 或 "group")
        index: 规则索引

    Returns:
        Rule | None: 被移除的规则, 如果索引无效则返回 None
    """
    settings = get_checker_plugin_settings(plugin_name)
    rules = settings.rules.private if rule_type == "private" else settings.rules.group

    if index < 0 or index >= len(rules):
        return None

    removed = rules[index]
    new_rules = [r for i, r in enumerate(rules) if i != index]

    if rule_type == "private":
        settings.rules.private = new_rules
    else:
        settings.rules.group = new_rules

    logger.info(f"Plugin '{plugin_name}' {rule_type} rule removed at index {index}")
    return removed


def clear_plugin_rules(
    plugin_name: str, rule_type: Literal["private", "group"] | None = None
) -> int:
    """
    清除插件规则.

    Args:
        plugin_name: 插件名称
        rule_type: 规则类型, None 表示清除所有规则

    Returns:
        int: 被清除的规则数量
    """
    settings = get_checker_plugin_settings(plugin_name)
    count = 0

    if rule_type is None or rule_type == "private":
        count += len(settings.rules.private)
        settings.rules.private = []

    if rule_type is None or rule_type == "group":
        count += len(settings.rules.group)
        settings.rules.group = []

    logger.info(
        f"Cleared {count} rules from plugin '{plugin_name}'"
        + (f" (type={rule_type})" if rule_type else " (all)")
    )
    return count
