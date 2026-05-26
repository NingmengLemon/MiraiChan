"""
权限检查 Node Factory.

将 LemonyChecker 包装为 melobot 的 @node 模式，使得权限检查可以直接在 Flow 中使用，
并在权限拒绝时能够直接发送回复消息。

原来的 Checker 形式问题：
- fail_cb 在每次不匹配的消息上都会触发，无法区分"为哪个 handler 拒绝"
- 无法直接在 checker 中发送"权限不足"回复
- 上下文信息只有 event，无法获取当前 Flow/command 信息

Node Factory 形式的优势：
- 直接在 node 内发送拒绝回复
- 享有完整的 melobot Flow 上下文（FlowCtx, ParseArgsCtx 等）
- 权限逻辑与业务逻辑清晰分离
"""

from collections.abc import Awaitable, Callable
from functools import wraps

from melobot import send_text
from melobot.adapter.model import Event
from melobot.handle import Flow, FlowNode, node

from .adapters.register import registry
from .core import check_command_permission, is_admin, is_owner
from .exceptions import LemonyProgrammingError
from .factory import LemonyCheckerFactory, get_checker_factory


class PermissionNodeFactory:
    """
    权限检查节点工厂.

    将 LemonyChecker 包装为 melobot @node 模式，使得权限检查可以：
    - 直接发送拒绝回复消息
    - 享有完整 Flow 上下文
    - 作为 Flow 中的一个节点灵活组合

    使用方式::

        from lemony_checkers import get_checker_factory
        from lemony_checkers.nodes import PermissionNodeFactory

        factory = get_checker_factory()
        perm = PermissionNodeFactory(factory)

        # 创建带权限检查的 Flow
        admin_flow = Flow("admin_cmd", [
            perm.create("my_plugin", "admin", deny_message="权限不足"),
            admin_handler_node,
        ], priority=10)
    """

    def __init__(self, factory: LemonyCheckerFactory) -> None:
        self._factory = factory

    def _is_allowed(
        self, event: Event, plugin_name: str, command_name: str | None
    ) -> bool:
        user = registry.extract_uniid_any(event)
        if user is None:
            return False
        return check_command_permission(
            global_settings=self._factory.global_settings,
            plugin_settings=self._factory.get_plugin_settings(plugin_name),
            user=user,
            command_name=command_name,
        )

    def create(
        self,
        plugin_name: str,
        command_name: str | None = None,
        *,
        deny_message: str = "❌ 权限不足",
        block: bool = True,
    ) -> FlowNode:
        """
        创建一个权限检查 FlowNode.

        Args:
            plugin_name: 插件名称，用于加载插件特定配置
            command_name: 命令名称（可选），用于命令级别的启停控制
            deny_message: 权限拒绝时发送的提示消息
            block: 是否阻断事件向低优先级 Flow 传播（默认 True）

        Returns:
            一个 melobot FlowNode，可作为 Flow 中的一个节点使用
        """

        @node(block=block)
        async def _check(event: Event) -> bool:
            if not self._is_allowed(event, plugin_name, command_name):
                await send_text(deny_message)
                return False
            return True

        return _check

    def create_with_fail_cb(
        self,
        plugin_name: str,
        command_name: str | None = None,
        *,
        fail_cb: Callable[[Event], Awaitable[None]] | None = None,
        block: bool = True,
    ) -> FlowNode:
        """
        创建一个带自定义失败回调的权限检查 FlowNode.

        与 create() 不同，此方法允许在权限拒绝时执行自定义逻辑
        （例如记录日志、发送不同格式的拒绝消息），而不仅仅是发送文本。

        Args:
            plugin_name: 插件名称
            command_name: 命令名称（可选）
            fail_cb: 权限拒绝时的自定义回调函数，接收事件对象
            block: 是否阻断事件传播

        Returns:
            一个 melobot FlowNode
        """

        @node(block=block)
        async def _check(event: Event) -> bool:
            if not self._is_allowed(event, plugin_name, command_name):
                if fail_cb is not None:
                    await fail_cb(event)
                return False
            return True

        return _check

    def make_flow(
        self,
        plugin_name: str,
        command_name: str | None = None,
        *,
        nodes: list[FlowNode],
        flow_name: str | None = None,
        priority: int = 0,
        deny_message: str = "❌ 权限不足",
        block: bool = True,
    ) -> Flow:
        """
        便捷方法：创建一个已内置权限检查节点的 Flow.

        Args:
            plugin_name: 插件名称
            command_name: 命令名称（可选）
            nodes: 业务逻辑节点列表（权限检查通过后执行）
            flow_name: Flow 名称，为空时自动生成
            priority: Flow 优先级
            deny_message: 权限拒绝消息
            block: 是否阻断事件传播

        Returns:
            一个 melobot Flow，第一个节点为权限检查，后续为业务节点
        """
        perm_node = self.create(
            plugin_name,
            command_name,
            deny_message=deny_message,
            block=block,
        )
        name = flow_name or f"perm_{plugin_name}" + (
            f"_{command_name}" if command_name else ""
        )
        return Flow(name, [perm_node, *nodes], priority=priority)


# ============================================================
# 便捷装饰器：可直接用于 @on_command / @on_text 等处理函数
# ============================================================


def _extract_event_from_args(*args, **kwargs) -> Event:
    """从 handler 参数中提取 Event 对象."""
    for arg in args:
        if isinstance(arg, Event):
            return arg
    for val in kwargs.values():
        if isinstance(val, Event):
            return val
    raise LemonyProgrammingError("No Event found in handler arguments")


def require_owner(deny_message: str | None = None):
    """
    装饰器：要求调用者必须是 Owner.

    使用方式::

        @on_command(".", " ", ["admin"])
        @require_owner()
        async def owner_only_cmd(event, adapter, args):
            ...

    Args:
        deny_message: 权限拒绝时发送的消息
    """

    def decorator(handler):
        @wraps(handler)
        async def wrapper(*args, **kwargs):
            event = _extract_event_from_args(*args, **kwargs)
            factory = get_checker_factory()
            user = registry.extract_uniid_any(event)
            if user is None or not is_owner(factory.global_settings, user):
                if deny_message:
                    await send_text(deny_message)
                return
            return await handler(*args, **kwargs)

        return wrapper

    return decorator


def require_admin(deny_message: str | None = None):
    """
    装饰器：要求调用者必须是 Owner 或 Admin.

    使用方式::

        @on_command(".", " ", ["manage"])
        @require_admin()
        async def admin_cmd(event, adapter, args):
            ...

    Args:
        deny_message: 权限拒绝时发送的消息
    """

    def decorator(handler):
        @wraps(handler)
        async def wrapper(*args, **kwargs):
            event = _extract_event_from_args(*args, **kwargs)
            factory = get_checker_factory()
            user = registry.extract_uniid_any(event)
            if user is None or not (
                is_owner(factory.global_settings, user)
                or is_admin(factory.global_settings, user)
            ):
                if deny_message:
                    await send_text(deny_message)
                return
            return await handler(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(
    plugin_name: str,
    command_name: str | None = None,
    *,
    deny_message: str | None = None,
):
    """
    装饰器：基于配置文件的权限检查.

    使用方式::

        @on_command(".", " ", ["mycmd"])
        @require_permission("my_plugin", "mycmd")
        async def my_command(event, adapter, args):
            ...

    Args:
        plugin_name: 插件名称，用于加载插件特定配置
        command_name: 命令名称（可选），用于命令级别的启停控制
        deny_message: 权限拒绝时发送的消息
    """

    def decorator(handler):
        @wraps(handler)
        async def wrapper(*args, **kwargs):
            event = _extract_event_from_args(*args, **kwargs)
            factory = get_checker_factory()
            user = registry.extract_uniid_any(event)
            plugin_settings = factory.get_plugin_settings(plugin_name)
            if user is None or not check_command_permission(
                global_settings=factory.global_settings,
                plugin_settings=plugin_settings,
                user=user,
                command_name=command_name,
            ):
                if deny_message:
                    await send_text(deny_message)
                return
            return await handler(*args, **kwargs)

        return wrapper

    return decorator
