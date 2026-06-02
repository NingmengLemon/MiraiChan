"""
Melobot checker adapters.

Framework-independent permission decisions live in ``core.py``. This
module only adapts those helpers to melobot's ``Checker`` interface and event
extraction model.
"""

import asyncio
from typing import TYPE_CHECKING

from melobot.adapter.model import Event
from melobot.log import get_logger
from melobot.typ import AsyncCallable
from melobot.utils.check import Checker

from .adapters.register import registry
from .core import check_command_permission

if TYPE_CHECKING:
    from .factory import LemonyCheckerFactory

logger = get_logger()


# 失败回调类型
type FailCallback = AsyncCallable[[], None]


class FailCallbackMixin:
    """
    提供 fail_cb 属性的 Mixin.

    方便在检查器中调用失败回调.
    """

    def __init__(self, fail_cb: FailCallback | None = None) -> None:
        self.fail_cb = fail_cb
        # 持有后台 Task 的强引用, 防止 GC 在 Task 完成前回收它.
        # 参见: https://docs.python.org/3/library/asyncio-task.html#creating-tasks
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def _call_fail_cb(self) -> None:
        """调用失败回调."""
        if self.fail_cb is not None:
            try:
                await self.fail_cb()
            except Exception as e:
                logger.error(f"Error in fail callback: {e}")

    def _fire_fail_cb(self) -> None:
        """fire-and-forget 调用失败回调, 避免阻塞检查流程.

        通过持有 Task 引用来防止 GC 提前回收 Task.
        """
        task = asyncio.create_task(self._call_fail_cb())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)


class LemonyChecker(Checker[Event], FailCallbackMixin):
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
        fail_cb: FailCallback | None = None,
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
        Checker.__init__(self, fail_cb=fail_cb)
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

    async def check(self, event: Event) -> bool:
        """
        执行权限检查.

        检查流程:
        1. 从事件提取 UniqueUser (通过协议适配器)
        2. Owner 始终通过
        3. 检查插件是否启用
        4. 检查命令是否启用
        5. Admin 检查 (如果启用)
        6. 按规则检查
        7. 根据 mode 决定默认行为

        Args:
            event: 事件

        Returns:
            bool: 是否通过检查
        """
        user = registry.extract_uniid_any(event)
        if user is None:
            logger.debug("Cannot extract user identity from event, check failed")
            self._fire_fail_cb()
            return False

        plugin_settings = (
            self._factory.get_plugin_settings(self._plugin_name)
            if self._plugin_name is not None
            else None
        )
        passed = check_command_permission(
            global_settings=self._factory.global_settings,
            plugin_settings=plugin_settings,
            user=user,
            command_name=self._command_name,
            allow_admin=self._allow_admin,
        )

        if not passed:
            logger.debug(
                f"User {user.to_tuple()} denied by checker"
                + (f" for plugin {self._plugin_name!r}" if self._plugin_name else "")
                + (f" command {self._command_name!r}" if self._command_name else "")
            )
            self._fire_fail_cb()

        return passed


class OwnerChecker(Checker[Event], FailCallbackMixin):
    """
    Owner 专用检查器.

    只有 Owner 可以通过检查.
    """

    def __init__(
        self, *, factory: "LemonyCheckerFactory", fail_cb: FailCallback | None = None
    ) -> None:
        Checker.__init__(self, fail_cb=fail_cb)
        FailCallbackMixin.__init__(self, fail_cb=fail_cb)

        self._factory = factory

    async def check(self, event: Event) -> bool:
        user = registry.extract_uniid_any(event)
        if user is None:
            self._fire_fail_cb()
            return False

        if self._factory.is_owner(user):
            return True

        self._fire_fail_cb()
        return False


class AdminChecker(Checker[Event], FailCallbackMixin):
    """
    Admin 检查器.

    Owner 和 Admin 都可以通过检查.
    """

    def __init__(
        self, *, factory: "LemonyCheckerFactory", fail_cb: FailCallback | None = None
    ) -> None:
        Checker.__init__(self, fail_cb=fail_cb)
        FailCallbackMixin.__init__(self, fail_cb=fail_cb)
        self._factory = factory

    async def check(self, event: Event) -> bool:
        user = registry.extract_uniid_any(event)
        if user is None:
            self._fire_fail_cb()
            return False

        if self._factory.is_owner(user) or self._factory.is_admin(user):
            return True

        self._fire_fail_cb()
        return False
