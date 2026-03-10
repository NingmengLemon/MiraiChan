"""
权限检查器实现.

提供基于配置的权限检查功能, 支持全局规则和插件特定规则.
"""

# TODO: support for more protocols
# 考虑更通用的设计以支持其他协议, 例如 Telegram, Discord 等. 可能需要抽象出一个通用的事件接口.

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Literal, Self

from melobot.log import get_logger
from melobot.protocols.onebot.v11 import GroupMessageEvent, MessageEvent
from melobot.utils.check import Checker

from .models import CheckerGlobalSettings, CheckerPluginSettings, Rule

if TYPE_CHECKING:
    from .factory import LemonyCheckerFactory

logger = get_logger()


class CheckResult(Enum):
    """检查结果枚举."""

    ALLOW = auto()  # 明确允许
    DENY = auto()  # 明确拒绝
    DEFAULT = auto()  # 使用默认行为 (根据 mode 决定)


# 失败回调类型
# 接收一个 MessageEvent 参数的 AsyncCallable
type FailCallback = Callable[[MessageEvent], Awaitable[Any]]


def _match_rules(
    rules: list[Rule],
    target_id: int,
) -> CheckResult:
    """
    按顺序匹配规则列表.

    Args:
        rules: 规则列表
        target_id: 要匹配的ID (用户ID或群组ID)

    Returns:
        CheckResult: 匹配结果
    """
    for rule in rules:
        # ids 为 None 表示匹配所有
        if rule.ids is None or target_id in rule.ids:
            if rule.action == "allow":
                return CheckResult.ALLOW
            else:
                return CheckResult.DENY

    return CheckResult.DEFAULT


def _check_rules(
    global_settings: CheckerGlobalSettings,
    plugin_settings: CheckerPluginSettings | None,
    user_id: int,
    group_id: int | None,
) -> CheckResult:
    """
    检查全局和插件规则.

    检查顺序:
    1. 全局规则 (私聊/群聊)
    2. 插件规则 (私聊/群聊)

    Args:
        global_settings: 全局配置
        plugin_settings: 插件配置 (可为 None)
        user_id: 用户ID
        group_id: 群组ID (私聊为 None)

    Returns:
        CheckResult: 检查结果
    """
    # 判断消息类型
    is_group = group_id is not None

    # 1. 检查全局规则
    if is_group:
        # 群聊: 先检查群组规则
        result = _match_rules(global_settings.rules.group_rules, group_id)
        if result != CheckResult.DEFAULT:
            return result
        # 再检查用户规则
        result = _match_rules(global_settings.rules.user_rules, user_id)
        if result != CheckResult.DEFAULT:
            return result
    else:
        # 私聊: 只检查用户规则
        result = _match_rules(global_settings.rules.user_rules, user_id)
        if result != CheckResult.DEFAULT:
            return result

    # 2. 检查插件规则
    if plugin_settings is not None:
        if is_group:
            result = _match_rules(plugin_settings.rules.group_rules, group_id)
            if result != CheckResult.DEFAULT:
                return result
            result = _match_rules(plugin_settings.rules.user_rules, user_id)
            if result != CheckResult.DEFAULT:
                return result
        else:
            result = _match_rules(plugin_settings.rules.user_rules, user_id)
            if result != CheckResult.DEFAULT:
                return result

    return CheckResult.DEFAULT


def _get_effective_mode(
    global_settings: CheckerGlobalSettings,
    plugin_settings: CheckerPluginSettings | None,
) -> Literal["whitelist", "blacklist"]:
    """
    获取有效的权限模式.

    插件配置的 mode 优先, 如果为 None 则使用全局配置.

    Args:
        global_settings: 全局配置
        plugin_settings: 插件配置 (可为 None)

    Returns:
        有效的权限模式
    """
    if plugin_settings is not None and plugin_settings.mode is not None:
        return plugin_settings.mode
    return global_settings.mode


class FailCallbackMixin:
    """
    提供 fail_cb 属性的 Mixin.

    方便在检查器中调用失败回调.
    """

    def __init__(self, fail_cb: FailCallback | None = None) -> None:
        self._fail_cb = fail_cb

    @property
    def fail_cb(self) -> FailCallback | None:
        """获取当前的失败回调."""
        return self._fail_cb

    def set_fail_cb(self, fail_cb: FailCallback) -> Self:
        """设置失败回调."""
        self._fail_cb = fail_cb
        return self  # 支持链式调用

    def clear_fail_cb(self) -> Self:
        """清除失败回调."""
        self._fail_cb = None
        return self  # 支持链式调用

    async def _call_fail_cb(self, event: MessageEvent) -> None:
        """调用失败回调."""
        if self._fail_cb is not None:
            try:
                await self._fail_cb(event)
            except Exception as e:
                logger.error(f"Error in fail callback: {e}")


class LemonyChecker(Checker[MessageEvent], FailCallbackMixin):
    """
    柠檬味的权限检查器.

    基于配置文件的权限检查, 支持:
    - 全局规则和插件特定规则
    - 白名单/黑名单模式
    - Owner 和 Admin 特权
    - 命令级别的启停控制
    - 自定义失败回调

    从 manager 获取 checker 实例, 而不是手动实例化这个类
    """

    def __init__(
        self,
        *,
        plugin_name: str | None,
        command_name: str | None,
        fail_cb: FailCallback | None,
        allow_admin: bool = True,
        factory: "LemonyCheckerFactory",
    ) -> None:
        """
        初始化检查器.

        Args:
            plugin_name: 插件名称, 用于加载插件特定配置. 为 None 时只使用全局配置.
            command_name: 命令名称, 用于命令级别的启停控制.
            fail_cb: 检查失败时的回调函数. 接收 event 参数.
            allow_admin: 是否允许管理员通过检查 (默认 True).
        """
        FailCallbackMixin.__init__(self, fail_cb=fail_cb)
        self._plugin_name = plugin_name
        self._command_name = command_name
        self._allow_admin = allow_admin
        self._factory = factory

    @property
    def plugin_name(self) -> str | None:
        return self._plugin_name

    @property
    def command_name(self) -> str | None:
        return self._command_name

    async def check(self, event: MessageEvent) -> bool:
        """
        执行权限检查.

        检查流程:
        1. Owner 始终通过
        2. 检查插件是否启用
        3. 检查命令是否启用
        4. Admin 检查 (如果启用)
        5. 按规则检查
        6. 根据 mode 决定默认行为

        Args:
            event: 消息事件

        Returns:
            bool: 是否通过检查
        """

        user_id = event.user_id

        # 1. Owner 始终通过
        if self._factory.is_owner(user_id):
            logger.debug(f"User {user_id} is owner, check passed")
            return True

        # 获取配置
        global_settings = self._factory.global_settings
        plugin_settings: CheckerPluginSettings | None = None

        if self._plugin_name is not None:
            plugin_settings = self._factory.get_plugin_settings(self._plugin_name)
            # 2. 检查插件是否启用
            if not plugin_settings.enabled:
                logger.debug(f"Plugin {self._plugin_name} is disabled")
                asyncio.create_task(self._call_fail_cb(event))
                return False

            # 3. 检查命令是否启用
            if self._command_name is not None:
                cmd_enabled = plugin_settings.commands.get(self._command_name, True)
                if not cmd_enabled:
                    logger.debug(
                        f"Command {self._command_name} in plugin {self._plugin_name} is disabled"
                    )
                    asyncio.create_task(self._call_fail_cb(event))
                    return False

        # 4. Admin 检查
        if self._allow_admin and self._factory.is_admin(user_id):
            logger.debug(f"User {user_id} is admin, check passed")
            return True

        # 获取群组ID (如果是群聊)
        group_id: int | None = None
        if isinstance(event, GroupMessageEvent):
            group_id = event.group_id

        # 5. 按规则检查
        result = _check_rules(global_settings, plugin_settings, user_id, group_id)

        # 6. 根据 mode 决定默认行为
        if result is CheckResult.DEFAULT:
            mode = _get_effective_mode(global_settings, plugin_settings)
            # whitelist 模式下默认拒绝, blacklist 模式下默认允许
            result = CheckResult.DENY if mode == "whitelist" else CheckResult.ALLOW

        passed = result is CheckResult.ALLOW

        if not passed:
            logger.debug(
                f"User {user_id} denied by checker"
                + (f" for plugin {self._plugin_name!r}" if self._plugin_name else "")
                + (f" command {self._command_name!r}" if self._command_name else "")
            )
            # fire and forget 调用失败回调, 避免阻塞检查流程
            asyncio.create_task(self._call_fail_cb(event))

        return passed


class OwnerChecker(Checker[MessageEvent], FailCallbackMixin):
    """
    Owner 专用检查器.

    只有 Owner 可以通过检查.
    """

    def __init__(
        self, *, factory: "LemonyCheckerFactory", fail_cb: FailCallback | None = None
    ) -> None:
        FailCallbackMixin.__init__(self, fail_cb=fail_cb)

        self._factory = factory

    async def check(self, event: MessageEvent) -> bool:
        if self._factory.is_owner(event.user_id):
            return True

        asyncio.create_task(self._call_fail_cb(event))
        return False


class AdminChecker(Checker[MessageEvent], FailCallbackMixin):
    """
    Admin 检查器.

    Owner 和 Admin 都可以通过检查.
    """

    def __init__(
        self, *, factory: "LemonyCheckerFactory", fail_cb: FailCallback | None = None
    ) -> None:
        FailCallbackMixin.__init__(self, fail_cb=fail_cb)
        self._factory = factory

    async def check(self, event: MessageEvent) -> bool:
        user_id = event.user_id

        if self._factory.is_owner(user_id) or self._factory.is_admin(user_id):
            return True

        asyncio.create_task(self._call_fail_cb(event))
        return False
