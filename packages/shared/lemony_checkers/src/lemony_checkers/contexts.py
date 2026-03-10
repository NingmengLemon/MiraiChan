from types import TracebackType
from typing import Literal, Self

from melobot.log import get_logger

from .factory import LemonyCheckerFactory
from .models import CheckerGlobalSettings, Rule

logger = get_logger()


class EditContext:
    def __init__(self, factory: LemonyCheckerFactory) -> None:
        self._factory = factory
        self._entered = False
        self._exited = False
        self._edited_global = False
        self._edited_plugins: set[str] = set()

    def __enter__(self) -> Self:
        self._entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # 只有在正常退出上下文时才保存修改, 如果发生异常则不保存.

        # XXX: 但是已经修改的配置要怎么回滚呢?
        # 目前的实现是直接不保存修改, 但这可能会导致部分修改被保留,
        # 部分修改未被保存的情况. 需要在工厂中实现一个回滚机制来彻底撤销未保存的修改.
        if exc_type is not None:
            logger.warning(
                f"Exiting edit context due to exception: {exc_value!r}. Changes will not be saved."
            )
            self._exited = True
            # return None (or other falsey value) to propagate the exception
            return
        if self._edited_global:
            self._factory.save_global_settings()
        for plugin_name in self._edited_plugins:
            self._factory.save_plugin_settings(plugin_name)
        self._exited = True

    @property
    def global_settings(self) -> CheckerGlobalSettings:
        if not self._entered or self._exited:
            raise RuntimeError(
                "Global settings can only be accessed within the context block."
            )
        return self._factory.global_settings

    # 配置修改与保存

    def set_owner(self, user_id: int | None) -> None:
        """
        设置机器人所有者.

        Args:
            user_id: 用户QQ号, 设为 None 可清除所有者
        """
        self.global_settings.owner = user_id
        logger.info(f"Owner set to: {user_id}")
        self._edited_global = True

    def add_admin(self, user_id: int) -> bool:
        """
        添加管理员.

        Args:
            user_id: 用户QQ号

        Returns:
            bool: 是否成功添加 (如果已存在则返回 False)
        """
        settings = self.global_settings
        if user_id in settings.admins:
            return False
        settings.admins = [*settings.admins, user_id]
        logger.info(f"Admin added: {user_id}")
        self._edited_global = True
        return True

    def remove_admin(self, user_id: int) -> bool:
        """
        移除管理员.

        Args:
            user_id: 用户QQ号

        Returns:
            bool: 是否成功移除 (如果不存在则返回 False)
        """
        settings = self.global_settings
        if user_id not in settings.admins:
            return False
        settings.admins = [uid for uid in settings.admins if uid != user_id]
        logger.info(f"Admin removed: {user_id}")
        self._edited_global = True
        return True

    def set_global_mode(self, mode: Literal["whitelist", "blacklist"]) -> None:
        """
        设置全局权限模式.

        Args:
            mode: 权限模式 ("whitelist" 或 "blacklist")
        """
        self.global_settings.mode = mode
        self._edited_global = True
        logger.info(f"Global mode set to: {mode}")

    def add_global_rule(
        self,
        rule_type: Literal["user", "group"],
        action: Literal["allow", "deny"],
        ids: list[int] | None = None,
    ) -> Rule:
        """
        添加全局规则.

        Args:
            rule_type: 规则类型 ("user" 用户规则, "group" 群组规则)
            action: 动作 ("allow" 允许, "deny" 拒绝)
            ids: ID列表 (用户ID或群组ID), None 表示匹配所有

        Returns:
            Rule: 添加的规则对象
        """
        settings = self.global_settings
        rule = Rule(action=action, ids=ids)

        if rule_type == "user":
            settings.rules.user_rules = [*settings.rules.user_rules, rule]
        else:
            settings.rules.group_rules = [*settings.rules.group_rules, rule]

        logger.info(f"Global {rule_type} rule added: action={action}, ids={ids}")
        self._edited_global = True
        return rule

    def remove_global_rule(
        self,
        rule_type: Literal["user", "group"],
        index: int,
    ) -> Rule | None:
        """
        移除指定索引的全局规则.

        Args:
            rule_type: 规则类型 ("user" 或 "group")
            index: 规则索引

        Returns:
            Rule | None: 被移除的规则, 如果索引无效则返回 None
        """
        settings = self.global_settings
        rules = (
            settings.rules.user_rules
            if rule_type == "user"
            else settings.rules.group_rules
        )

        if index < 0 or index >= len(rules):
            return None

        removed = rules[index]
        new_rules = [r for i, r in enumerate(rules) if i != index]

        if rule_type == "user":
            settings.rules.user_rules = new_rules
        else:
            settings.rules.group_rules = new_rules

        logger.info(f"Global {rule_type} rule removed at index {index}")
        self._edited_global = True
        return removed

    def clear_global_rules(
        self,
        rule_type: Literal["user", "group"] | None,
        # 三个值是等价的选择, 于是不添加默认值
    ) -> int:
        """
        清除全局规则.

        Args:
            rule_type: 规则类型, None 表示清除所有规则

        Returns:
            int: 被清除的规则数量
        """
        settings = self.global_settings
        count = 0

        if rule_type is None or rule_type == "user":
            count += len(settings.rules.user_rules)
            settings.rules.user_rules = []

        if rule_type is None or rule_type == "group":
            count += len(settings.rules.group_rules)
            settings.rules.group_rules = []

        logger.info(
            f"Cleared {count} global rules"
            + (f" (type={rule_type})" if rule_type else " (all)")
        )
        self._edited_global = True
        return count

    def set_plugin_enabled(self, plugin_name: str, enabled: bool) -> None:
        """
        设置插件是否启用.

        Args:
            plugin_name: 插件名称
            enabled: 是否启用
        """
        self._factory.get_plugin_settings(plugin_name).enabled = enabled
        logger.info(f"Plugin '{plugin_name}' enabled set to: {enabled}")
        self._edited_plugins.add(plugin_name)

    def set_plugin_mode(
        self, plugin_name: str, mode: Literal["whitelist", "blacklist"] | None
    ) -> None:
        """
        设置插件权限模式.

        Args:
            plugin_name: 插件名称
            mode: 权限模式, None 表示使用全局模式
        """
        self._factory.get_plugin_settings(plugin_name).mode = mode
        logger.info(f"Plugin '{plugin_name}' mode set to: {mode}")
        self._edited_plugins.add(plugin_name)

    def set_command_enabled(
        self, plugin_name: str, command_name: str, enabled: bool
    ) -> None:
        """
        设置命令是否启用.

        Args:
            plugin_name: 插件名称
            command_name: 命令名称
            enabled: 是否启用
        """
        settings = self._factory.get_plugin_settings(plugin_name)
        settings.commands = {**settings.commands, command_name: enabled}
        logger.info(
            f"Command '{command_name}' in plugin '{plugin_name}' enabled set to: {enabled}"
        )
        self._edited_plugins.add(plugin_name)

    def remove_command_setting(self, plugin_name: str, command_name: str) -> bool:
        """
        移除命令的启用设置 (恢复为默认启用).

        Args:
            plugin_name: 插件名称
            command_name: 命令名称

        Returns:
            bool: 是否成功移除 (如果不存在则返回 False)
        """
        settings = self._factory.get_plugin_settings(plugin_name)
        if command_name not in settings.commands:
            return False
        settings.commands = {
            k: v for k, v in settings.commands.items() if k != command_name
        }
        logger.info(
            f"Command '{command_name}' setting removed from plugin '{plugin_name}'"
        )
        self._edited_plugins.add(plugin_name)
        return True

    def add_plugin_rule(
        self,
        plugin_name: str,
        rule_type: Literal["user", "group"],
        action: Literal["allow", "deny"],
        ids: list[int] | None = None,
    ) -> Rule:
        """
        添加插件规则.

        Args:
            plugin_name: 插件名称
            rule_type: 规则类型 ("user" 用户规则, "group" 群组规则)
            action: 动作 ("allow" 允许, "deny" 拒绝)
            ids: ID列表 (用户ID或群组ID), None 表示匹配所有

        Returns:
            Rule: 添加的规则对象
        """
        settings = self._factory.get_plugin_settings(plugin_name)
        rule = Rule(action=action, ids=ids)

        if rule_type == "user":
            settings.rules.user_rules = [*settings.rules.user_rules, rule]
        else:
            settings.rules.group_rules = [*settings.rules.group_rules, rule]

        logger.info(
            f"Plugin '{plugin_name}' {rule_type} rule added: action={action}, ids={ids}"
        )
        self._edited_plugins.add(plugin_name)
        return rule

    def remove_plugin_rule(
        self,
        plugin_name: str,
        rule_type: Literal["user", "group"],
        index: int,
    ) -> Rule | None:
        """
        移除指定索引的插件规则.

        Args:
            plugin_name: 插件名称
            rule_type: 规则类型 ("user" 或 "group")
            index: 规则索引

        Returns:
            Rule | None: 被移除的规则, 如果索引无效则返回 None
        """
        settings = self._factory.get_plugin_settings(plugin_name)
        rules = (
            settings.rules.user_rules
            if rule_type == "user"
            else settings.rules.group_rules
        )

        if index < 0 or index >= len(rules):
            return None

        removed = rules[index]
        new_rules = [r for i, r in enumerate(rules) if i != index]

        if rule_type == "user":
            settings.rules.user_rules = new_rules
        else:
            settings.rules.group_rules = new_rules

        logger.info(f"Plugin '{plugin_name}' {rule_type} rule removed at index {index}")
        self._edited_plugins.add(plugin_name)
        return removed

    def clear_plugin_rules(
        self, plugin_name: str, rule_type: Literal["user", "group"] | None
    ) -> int:
        """
        清除插件规则.

        Args:
            plugin_name: 插件名称
            rule_type: 规则类型, None 表示清除所有规则

        Returns:
            int: 被清除的规则数量
        """
        settings = self._factory.get_plugin_settings(plugin_name)
        count = 0

        if rule_type is None or rule_type == "user":
            count += len(settings.rules.user_rules)
            settings.rules.user_rules = []

        if rule_type is None or rule_type == "group":
            count += len(settings.rules.group_rules)
            settings.rules.group_rules = []

        logger.info(
            f"Cleared {count} rules from plugin '{plugin_name}'"
            + (f" (type={rule_type})" if rule_type else " (all)")
        )
        self._edited_plugins.add(plugin_name)
        return count
