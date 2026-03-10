"""Telegram 事件处理装饰器

提供类似 melobot.protocols.onebot.v11.handle 的装饰器，用于绑定事件处理器。
"""

from __future__ import annotations

from melobot.handle import FlowDecorator
from melobot.handle import on_event as _on_event
from melobot.typ import SyncOrAsyncCallable
from melobot.utils.check import Checker

from .adapter.event import (
    CallbackQueryEvent,
    ChannelPostEvent,
    ChatMemberEvent,
    EditedMessageEvent,
    Event,
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)


def on_event(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理所有 Telegram 事件"""
    return _on_event(checker=checker, priority=priority, block=block, temp=temp)


def on_message(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理 Telegram 消息事件（包括私聊和群组）"""

    def _type_check(event: Event) -> bool:
        return isinstance(event, MessageEvent)

    inner_checker: Checker | SyncOrAsyncCallable[..., bool]
    if checker is not None:
        inner_checker = _combine_checkers(_type_check, checker)
    else:
        inner_checker = Checker.new(_type_check)

    return _on_event(checker=inner_checker, priority=priority, block=block, temp=temp)


def on_private_message(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理 Telegram 私聊消息事件"""

    def _type_check(event: Event) -> bool:
        return isinstance(event, PrivateMessageEvent)

    inner_checker: Checker | SyncOrAsyncCallable[..., bool]
    if checker is not None:
        inner_checker = _combine_checkers(_type_check, checker)
    else:
        inner_checker = Checker.new(_type_check)

    return _on_event(checker=inner_checker, priority=priority, block=block, temp=temp)


def on_group_message(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理 Telegram 群组消息事件"""

    def _type_check(event: Event) -> bool:
        return isinstance(event, GroupMessageEvent)

    inner_checker: Checker | SyncOrAsyncCallable[..., bool]
    if checker is not None:
        inner_checker = _combine_checkers(_type_check, checker)
    else:
        inner_checker = Checker.new(_type_check)

    return _on_event(checker=inner_checker, priority=priority, block=block, temp=temp)


def on_callback_query(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理 Telegram 回调查询事件（按钮点击）"""

    def _type_check(event: Event) -> bool:
        return isinstance(event, CallbackQueryEvent)

    inner_checker: Checker | SyncOrAsyncCallable[..., bool]
    if checker is not None:
        inner_checker = _combine_checkers(_type_check, checker)
    else:
        inner_checker = Checker.new(_type_check)

    return _on_event(checker=inner_checker, priority=priority, block=block, temp=temp)


def on_edited_message(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理 Telegram 消息编辑事件"""

    def _type_check(event: Event) -> bool:
        return isinstance(event, EditedMessageEvent)

    inner_checker: Checker | SyncOrAsyncCallable[..., bool]
    if checker is not None:
        inner_checker = _combine_checkers(_type_check, checker)
    else:
        inner_checker = Checker.new(_type_check)

    return _on_event(checker=inner_checker, priority=priority, block=block, temp=temp)


def on_channel_post(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理 Telegram 频道帖子事件"""

    def _type_check(event: Event) -> bool:
        return isinstance(event, ChannelPostEvent)

    inner_checker: Checker | SyncOrAsyncCallable[..., bool]
    if checker is not None:
        inner_checker = _combine_checkers(_type_check, checker)
    else:
        inner_checker = Checker.new(_type_check)

    return _on_event(checker=inner_checker, priority=priority, block=block, temp=temp)


def on_chat_member(
    checker: Checker | SyncOrAsyncCallable[..., bool] | None = None,
    priority: int = 0,
    block: bool = False,
    temp: bool = False,
) -> FlowDecorator:
    """处理 Telegram 聊天成员变动事件"""

    def _type_check(event: Event) -> bool:
        return isinstance(event, ChatMemberEvent)

    inner_checker: Checker | SyncOrAsyncCallable[..., bool]
    if checker is not None:
        inner_checker = _combine_checkers(_type_check, checker)
    else:
        inner_checker = Checker.new(_type_check)

    return _on_event(checker=inner_checker, priority=priority, block=block, temp=temp)


def _combine_checkers(
    type_check: SyncOrAsyncCallable[..., bool],
    user_checker: Checker | SyncOrAsyncCallable[..., bool],
) -> Checker:
    """将类型检查和用户检查器组合"""
    from melobot.utils.check import checker_join

    type_checker = Checker.new(type_check)
    if isinstance(user_checker, Checker):
        return checker_join(type_checker, user_checker)
    return checker_join(type_checker, Checker.new(user_checker))
