"""扩展 action 的公共基类与调用助手

实现端 (SnowLuma / NapCat / Lagrange 等) 在 OneBot 11 之外各自加了一批 action。melobot 只内置
标准 action, 这里用统一的方式把它们包起来: 子类给出 action 名与参数, :func:`call_extension` 负责
发出去并检查回应。

设计要点:

- action 名与参数集中在子类里, 插件侧只看到关键字参数, 不接触 ``{"action": ..., "params": ...}``
- 失败用 :class:`ExtensionError` 抛出, 带上 action 名与 retcode; 需要"不支持就算了"时用
  :func:`try_extension`, 失败返回 ``None``
- 这些 action 不是标准, 是否支持由实现端决定, 支持情况记录在 :mod:`catalog`
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Protocol

from melobot.exceptions import ActionHandleError
from melobot.protocols.onebot.v11.adapter.action import Action
from melobot.protocols.onebot.v11.adapter.echo import Echo

__all__ = [
    "CallOutput",
    "ExtensionAction",
    "ExtensionError",
    "call_extension",
    "try_extension",
]

logger = logging.getLogger(__name__)


class CallOutput(Protocol):
    """只要求 ``call_output`` 的适配器协议, 测试可以传假件"""

    async def call_output(self, action: Action) -> Any: ...


class ExtensionAction(Action):
    """一个实现端扩展 action 的基类

    ``echo_cls`` 用于声明专用回应类型: adapter 只按标准 action 名分派 echo, 未知 action 一律
    返回通用 :class:`Echo`, 所以带结构的回应要靠这里重新组装。
    """

    action_name: ClassVar[str]
    echo_cls: ClassVar[type[Echo] | None] = None

    def __init__(self, **params: object) -> None:
        super().__init__(self.action_name, params)


class ExtensionError(RuntimeError):
    """扩展 action 调用失败 (不是标准 action, 或者被实现端拒绝)"""

    def __init__(self, action: str, retcode: int | None) -> None:
        self.action = action
        self.retcode = retcode
        detail = "没有回应" if retcode is None else f"retcode={retcode}"
        super().__init__(f"{action} 调用失败 ({detail})")


async def call_extension(adapter: CallOutput, action: ExtensionAction) -> Echo:
    """调用一个扩展 action, 失败抛 :class:`ExtensionError`"""
    group = await adapter.call_output(action)
    try:
        echo = await group.unwrap(0)
    except ActionHandleError as exc:
        raise ExtensionError(action.action_name, None) from exc
    if echo is None:
        raise ExtensionError(action.action_name, None)
    if not echo.is_ok():
        # 根 Echo.status 存的就是 OneBot 的 retcode
        raise ExtensionError(action.action_name, echo.status)
    if (echo_cls := action.echo_cls) is not None and not isinstance(echo, echo_cls):
        raw = dict(echo.raw)
        raw["action_type"] = action.action_name
        echo = echo_cls(**raw)
    return echo


async def try_extension(adapter: CallOutput, action: ExtensionAction) -> Echo | None:
    """调用一个扩展 action; 失败或实现端不支持时返回 ``None``

    适合"贴个 reaction 之类, 失败就退回别的表现"的场景。
    """
    try:
        return await call_extension(adapter, action)
    except Exception:
        logger.debug("扩展 action %s 不可用", action.action_name, exc_info=True)
        return None
