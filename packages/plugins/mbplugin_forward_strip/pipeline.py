"""把"取转发 -> 切片 -> 重新发送"串起来

IO 全部走注入的 ``ForwardIo``, 所以这里可以用假实现测试, 不依赖 melobot 与协议端。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .nodes import (
    ForwardNode,
    SliceSpecError,
    count_nested_forwards,
    find_forward_id,
    from_payload,
    parse_slice,
    to_payload,
)

__all__ = ["ForwardIo", "StripError", "StripResult", "strip_forward"]


class StripError(ValueError):
    """可以回给用户看的错误"""


class ForwardIo(Protocol):
    async def get_message_segments(self, message_id: int) -> Sequence[Any]: ...

    async def get_forward_nodes(self, forward_id: str) -> Sequence[Any]: ...

    async def send_forward_nodes(
        self, group_id: int, nodes: Sequence[dict[str, Any]]
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StripResult:
    total: int
    kept: int
    nested: int


def _nodes_of(raw: Sequence[Any]) -> list[ForwardNode]:
    nodes: list[ForwardNode] = []
    for item in raw:
        node = from_payload(
            item if isinstance(item, dict) else {"type": item.type, "data": item.data}
        )
        if node is not None:
            nodes.append(node)
    return nodes


async def strip_forward(
    io: ForwardIo,
    *,
    group_id: int,
    reply_message_id: int,
    spec: str,
    max_nodes: int = 100,
) -> StripResult:
    """对着一条含合并转发的消息做切片, 再发回来"""
    segments = await io.get_message_segments(reply_message_id)
    forward_id = find_forward_id(segments)
    if forward_id is None:
        raise StripError("这条消息里没有合并转发, 回一条转发消息再试")
    try:
        code = parse_slice(spec)
    except SliceSpecError as exc:
        raise StripError(str(exc)) from exc

    nodes = _nodes_of(await io.get_forward_nodes(forward_id))
    if not nodes:
        raise StripError("转发里没有可用的消息节点")
    kept = nodes[code]
    if not kept:
        raise StripError(f"切片「{spec}」之后一条都不剩了")
    if len(kept) > max_nodes:
        raise StripError(f"截完还有 {len(kept)} 条, 超过 {max_nodes} 条的上限")

    # 按原样发, 每条消息的昵称和头像保持原主。
    # 嵌套转发发不出去时宁可报错, 不发一条缺了内容的记录
    nested = sum(count_nested_forwards(node) for node in kept)
    payload = [to_payload(node) for node in kept]
    try:
        await io.send_forward_nodes(group_id, payload)
    except Exception as exc:
        if nested:
            raise StripError(
                f"发送失败: 保留的节点里有 {nested} 处嵌套转发, 当前实现端可能不支持, "
                "没有发送残缺的记录"
            ) from exc
        raise StripError("转发没有发出去") from exc
    return StripResult(total=len(nodes), kept=len(kept), nested=nested)
