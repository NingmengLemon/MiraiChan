from types import TracebackType
from typing import Literal, Self

from melobot.log import get_logger
from pydantic import BaseModel

from .factory import LemonyCheckerFactory
from .models import CheckerGlobalSettings, CheckerPluginSettings, Rule

logger = get_logger()


class EditContext:
    """编辑配置的上下文管理器.

    在上下文块中修改配置, 正常退出时自动保存, 异常退出时回滚所有修改.

    使用 ``copy.deepcopy`` 在进入上下文时对全局配置和已访问的插件配置做快照,
    异常退出时恢复快照以保证内存中的配置状态一致性.
    """

    def __init__(self, factory: LemonyCheckerFactory) -> None:
        self._factory = factory
        self._entered = False
        self._exited = False
        self._edited_global = False
        self._edited_plugins: set[str] = set()
        # 快照: 用于异常时回滚
        self._global_snapshot: CheckerGlobalSettings | None = None
        self._plugin_snapshots: dict[str, CheckerPluginSettings] = {}

    def __enter__(self) -> Self:
        self._entered = True
        # 对全局配置做快照
        self._global_snapshot = self._factory.global_settings.model_copy(deep=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # 只有在正常退出上下文时才保存修改, 如果发生异常则回滚.
        if exc_type is not None:
            logger.warning(
                f"Exiting edit context due to exception: {exc_value!r}. "
                "Rolling back in-memory changes."
            )
            self._rollback()
            self._exited = True
            # return None (or other falsey value) to propagate the exception
            return
        if self._edited_global:
            self._factory.save_global_settings()
        for plugin_name in self._edited_plugins:
            self._factory.save_plugin_settings(plugin_name)
        self._exited = True

    @staticmethod
    def _restore_model_fields(target: BaseModel, snapshot: BaseModel) -> None:
        """从快照恢复模型的所有字段值."""
        for field_name in snapshot.__class__.model_fields:
            setattr(target, field_name, getattr(snapshot, field_name))

    def _rollback(self) -> None:
        """回滚内存中的配置到进入上下文时的快照状态."""
        # 回滚全局配置
        if self._global_snapshot is not None:
            self._restore_model_fields(
                self._factory.global_settings, self._global_snapshot
            )
            logger.debug("Rolled back global settings to snapshot")

        # 回滚插件配置
        for plugin_name, snapshot in self._plugin_snapshots.items():
            try:
                ps = self._factory.get_plugin_settings(plugin_name)
                self._restore_model_fields(ps, snapshot)
                logger.debug(f"Rolled back plugin '{plugin_name}' settings to snapshot")
            except Exception as e:
                logger.error(f"Failed to rollback plugin '{plugin_name}' settings: {e}")

    def _ensure_plugin_snapshot(self, plugin_name: str) -> None:
        """确保指定插件的配置快照已创建 (仅在首次修改该插件时创建)."""
        if plugin_name not in self._plugin_snapshots:
            self._plugin_snapshots[plugin_name] = self._factory.get_plugin_settings(
                plugin_name
            ).model_copy(deep=True)

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

    def set_global_rule_priority(
        self, priority: Literal["group_first", "user_first"]
    ) -> None:
        """
        设置全局规则匹配优先级.

        Args:
            priority: 匹配优先级 ("group_first" 或 "user_first")
        """
        self.global_settings.rule_priority = priority
        self._edited_global = True
        logger.info(f"Global rule priority set to: {priority}")

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
        self._ensure_plugin_snapshot(plugin_name)
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
        self._ensure_plugin_snapshot(plugin_name)
        self._factory.get_plugin_settings(plugin_name).mode = mode
        logger.info(f"Plugin '{plugin_name}' mode set to: {mode}")
        self._edited_plugins.add(plugin_name)

    def set_plugin_rule_priority(
        self,
        plugin_name: str,
        priority: Literal["group_first", "user_first"] | None,
    ) -> None:
        """
        设置插件的规则匹配优先级.

        Args:
            plugin_name: 插件名称
            priority: 匹配优先级, None 表示使用全局配置
        """
        self._ensure_plugin_snapshot(plugin_name)
        self._factory.get_plugin_settings(plugin_name).rule_priority = priority
        logger.info(f"Plugin '{plugin_name}' rule priority set to: {priority}")
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
        self._ensure_plugin_snapshot(plugin_name)
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
        self._ensure_plugin_snapshot(plugin_name)
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
        self._ensure_plugin_snapshot(plugin_name)
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
        self._ensure_plugin_snapshot(plugin_name)
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
        self._ensure_plugin_snapshot(plugin_name)
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
