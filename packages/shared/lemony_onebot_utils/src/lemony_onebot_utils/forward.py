"""合并转发消息的便捷构造.

插件开发者只关心"谁说了什么", 不必手写 ``NodeSegment`` 的那堆参数::

    fwd = ForwardBuilder(Sender.of_event(event))
    fwd.text("第一条")
    fwd.text(long_text)                 # 超长文本自动拆成多个节点
    fwd.add([TextSegment("图文"), ImageSegment(file=url)])
    fwd.refer(message_id)               # 引用一条已有消息
    fwd.text("换个人说", sender=Sender(10001, "路人"))
    await fwd.send(adapter)             # 发到当前事件所在会话

没有事件上下文时 (定时任务、外部推送) 显式指定会话::

    sender = await Sender.of_bot(adapter)
    await ForwardBuilder(sender).text(report).send_to(adapter, group_id=gid)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Self

from melobot.handle import try_get_event
from melobot.protocols.onebot.v11 import MessageEvent
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.echo import SendForwardMsgEcho
from melobot.protocols.onebot.v11.adapter.segment import (
    NodeSegment,
    Segment,
    TextSegment,
)

__all__ = [
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_NODE_TEXT",
    "ForwardBuilder",
    "ForwardTooLargeError",
    "Sender",
    "split_text",
]

#: 单个节点的文本上限. 协议端对单条消息长度有限制, 留出余量
DEFAULT_MAX_NODE_TEXT = 4500
#: 单条合并转发的节点数上限. QQ 客户端对超过约 100 个节点的转发显示不全
DEFAULT_MAX_NODES = 100


class ForwardTooLargeError(ValueError):
    """节点数超过上限"""


@dataclass(frozen=True, slots=True)
class Sender:
    """节点上显示的发言人. 这只是显示用的名片, 不要求真的是这个人发的"""

    user_id: int
    nickname: str

    @classmethod
    def of_event(cls, event: MessageEvent | None = None) -> Sender:
        """取消息事件的发送者; 不传时取当前上下文中的事件"""
        if event is None:
            got = try_get_event()
            if not isinstance(got, MessageEvent):
                raise LookupError("当前上下文中没有消息事件, 请显式指定 Sender")
            event = got
        uid = (
            event.sender.user_id if event.sender.user_id is not None else event.user_id
        )
        return cls(uid, event.sender.nickname or str(uid))

    @classmethod
    async def of_bot(cls, adapter: Adapter) -> Sender:
        """取 bot 自己的账号与昵称"""
        echo = await (await adapter.get_login_info()).unwrap(0)
        if echo.data is None:
            raise LookupError("get_login_info 没有返回数据")
        return cls(echo.data["user_id"], echo.data["nickname"])


def split_text(text: str, max_len: int = DEFAULT_MAX_NODE_TEXT) -> list[str]:
    """把文本切成不超过 ``max_len`` 的若干段.

    优先在换行处断开, 一行本身就超长时才硬切; 空文本返回空列表.
    """
    if max_len < 1:
        raise ValueError("max_len must be positive")
    chunks: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        while len(line) > max_len:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:max_len])
            line = line[max_len:]
        if len(buf) + len(line) > max_len:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    # 段尾换行在转发节点里只会变成多余的空行
    return [c.rstrip("\n") for c in chunks if c.strip("\n")]


def _node(sender: Sender, content: list[Segment], *, use_std: bool) -> NodeSegment:
    return NodeSegment(
        uin=sender.user_id, name=sender.nickname, content=content, use_std=use_std
    )


def _refer_node(message_id: int | str) -> NodeSegment:
    # melobot 3.5 的 NodeSegment(id=...) / NodeReferSegment(...) 会因为缺 use_std / content
    # 抛 KeyError, 这里把它们补上; 引用节点序列化后只剩 id
    return NodeSegment(id=str(message_id), use_std=False, content=[])  # ty: ignore[no-matching-overload]


class ForwardBuilder:
    """按顺序收集转发节点, 最后一次性发出.

    Args:
        sender: 默认发言人; 为 None 时取当前上下文中消息事件的发送者 (首次需要时才取)
        use_std: True 生成 OneBot 标准节点 (``user_id``/``nickname``),
            False 生成 go-cqhttp 风格 (``uin``/``name``). 主流协议端两种都认
        max_node_text: 单个文本节点的长度上限, ``text()`` 据此自动拆分
        max_nodes: 节点数上限, 超过时 ``build()`` 抛 ``ForwardTooLargeError``
    """

    def __init__(
        self,
        sender: Sender | None = None,
        *,
        use_std: bool = True,
        max_node_text: int = DEFAULT_MAX_NODE_TEXT,
        max_nodes: int = DEFAULT_MAX_NODES,
    ) -> None:
        self._sender = sender
        self._use_std = use_std
        self._max_node_text = max_node_text
        self._max_nodes = max_nodes
        self._nodes: list[NodeSegment] = []

    def __len__(self) -> int:
        return len(self._nodes)

    def _resolve(self, sender: Sender | None) -> Sender:
        if sender is not None:
            return sender
        if self._sender is None:
            self._sender = Sender.of_event()
        return self._sender

    def text(self, text: str, *, sender: Sender | None = None) -> Self:
        """添加文本; 超长时拆成多个节点, 空文本忽略"""
        who = self._resolve(sender)
        for chunk in split_text(text, self._max_node_text):
            self._nodes.append(_node(who, [TextSegment(chunk)], use_std=self._use_std))
        return self

    def texts(self, texts: Iterable[str], *, sender: Sender | None = None) -> Self:
        """每段文本各占至少一个节点"""
        for t in texts:
            self.text(t, sender=sender)
        return self

    def add(
        self,
        content: str | Segment | Sequence[Segment],
        *,
        sender: Sender | None = None,
    ) -> Self:
        """添加一个节点, 内容原样放入 (不拆分). 适合图文混排"""
        if isinstance(content, str):
            segs: list[Segment] = [TextSegment(content)]
        elif isinstance(content, Segment):
            segs = [content]
        else:
            segs = list(content)
        if not segs:
            raise ValueError("节点内容不能为空")
        self._nodes.append(_node(self._resolve(sender), segs, use_std=self._use_std))
        return self

    def refer(self, message_id: int | str) -> Self:
        """引用一条已存在的消息 (显示原发送者与原内容)"""
        self._nodes.append(_refer_node(message_id))
        return self

    def extend(self, other: ForwardBuilder) -> Self:
        """把另一个 builder 的节点接在后面"""
        self._nodes.extend(other._nodes)
        return self

    def build(self) -> list[NodeSegment]:
        if not self._nodes:
            raise ValueError("转发消息没有任何节点")
        if len(self._nodes) > self._max_nodes:
            raise ForwardTooLargeError(
                f"转发节点数 {len(self._nodes)} 超过上限 {self._max_nodes}"
            )
        return list(self._nodes)

    async def send(self, adapter: Adapter) -> SendForwardMsgEcho | None:
        """发到当前消息事件所在的会话 (群聊或私聊)"""
        handles = await adapter.send_forward(self.build())
        return await handles[0]

    async def send_to(
        self,
        adapter: Adapter,
        *,
        group_id: int | None = None,
        user_id: int | None = None,
    ) -> SendForwardMsgEcho | None:
        """发到指定会话; ``group_id`` 与 ``user_id`` 必须恰好给一个"""
        if (group_id is None) == (user_id is None):
            raise ValueError("group_id 与 user_id 必须恰好指定一个")
        handles = await adapter.send_forward_custom(
            self.build(), user_id=user_id, group_id=group_id
        )
        return await handles[0]
