"""合并转发节点的归一化、切片与再序列化

这里不碰 melobot / OneBot 客户端, 只处理"节点字典"这一层, 便于单独测试。

节点有两种自定义形状, 两种都认:

- OneBot 标准: ``{"type": "node", "data": {"user_id", "nickname", "content"}}``
- go-cqhttp:   ``{"type": "node", "data": {"uin", "name", "content"}}``

另外还有只有 ``id`` 的引用节点, 它引用一条已存在的消息, 再发送时由协议端自己补内容。
发送时统一按原样回填, 保证被截断后每条消息的昵称与头像还是原来那个人。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ForwardNode",
    "SegmentDict",
    "SliceSpecError",
    "count_nested_forwards",
    "find_forward_id",
    "forward_items",
    "from_payload",
    "parse_slice",
    "to_payload",
]

SegmentDict = dict[str, Any]

_SLICE_RE = re.compile(
    r"^\s*\[?\s*([^]:]*)\s*(?::\s*([^]:]*)\s*)?(?::\s*([^]]*?)\s*)?\]?\s*$"
)


class SliceSpecError(ValueError):
    """切片写法看不懂, message 直接面向用户"""


@dataclass(frozen=True, slots=True)
class ForwardNode:
    """一条转发消息的发送者信息与内容, 原样保存以便回填"""

    content: tuple[SegmentDict, ...]
    uin: int | None = None
    name: str | None = None
    time: int | None = None
    # 只有 id 的引用节点
    refer_id: str | None = None

    @property
    def is_refer(self) -> bool:
        return self.refer_id is not None

    def describe(self, index: int) -> str:
        who = self.name or ("引用 " + str(self.refer_id) if self.is_refer else "未知")
        return f"{index}. {who}: {_preview(self.content)}"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _segments(items: Iterable[Any]) -> tuple[SegmentDict, ...]:
    out: list[SegmentDict] = []
    for item in items:
        if isinstance(item, Mapping):
            out.append(
                {
                    "type": str(item.get("type", "")),
                    "data": dict(item.get("data") or {}),
                }
            )
        else:
            # melobot 的 Segment 对象: type + data
            seg_type = getattr(item, "type", "")
            seg_data = getattr(item, "data", None)
            if seg_data is None:
                continue
            out.append({"type": str(seg_type), "data": dict(seg_data)})
    return tuple(out)


def from_payload(payload: Mapping[str, Any]) -> ForwardNode | None:
    """一条 node 消息段 -> ForwardNode; 不是 node 时返回 None"""
    if str(payload.get("type")) != "node":
        return None
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    if (refer := data.get("id")) is not None:
        return ForwardNode(content=(), refer_id=str(refer))
    content = data.get("content", data.get("message", ()))
    if isinstance(content, str):
        content = ({"type": "text", "data": {"text": content}},)
    return ForwardNode(
        content=_segments(content or ()),
        uin=_int_or_none(data.get("uin", data.get("user_id"))),
        name=_name_of(data),
        time=_int_or_none(data.get("time")),
    )


def from_forward_item(item: Mapping[str, Any]) -> ForwardNode | None:
    """get_forward_msg 返回数组里的一项 -> ForwardNode

    两种形状都见得到:

    - node 消息段 (go-cqhttp / OneBot 标准实现的典型返回)
    - 消息事件 (SnowLuma 的返回: ``message_id`` / ``sender`` / ``message`` / ``time``),
      发送者信息在 ``sender.user_id``、``sender.card`` 或 ``sender.nickname`` 上
    """
    if (node := from_payload(item)) is not None:
        return node
    content = item.get("message", item.get("content", ()))
    if isinstance(content, str):
        content = ({"type": "text", "data": {"text": content}},)
    if not content and item.get("message_id") is None:
        return None
    sender = item.get("sender")
    sender = sender if isinstance(sender, Mapping) else {}
    uin = _int_or_none(sender.get("user_id", item.get("user_id", item.get("uin"))))
    name = _name_of(sender) or _name_of(item)
    return ForwardNode(
        content=_segments(content or ()),
        uin=uin,
        name=name,
        time=_int_or_none(item.get("time")),
    )


def _name_of(data: Mapping[str, Any]) -> str | None:
    for key in ("name", "card", "nickname"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def to_payload(node: ForwardNode) -> SegmentDict:
    """回填成 node 消息段。带 uin/name 的用 go-cqhttp 形状, 服务端两种都认"""
    if node.is_refer:
        return {"type": "node", "data": {"id": node.refer_id}}
    data: SegmentDict = {"content": [dict(seg) for seg in node.content]}
    if node.uin is not None:
        data["uin"] = node.uin
    if node.name is not None:
        data["name"] = node.name
    if node.time is not None:
        data["time"] = node.time
    return {"type": "node", "data": data}


def _preview(content: Sequence[Mapping[str, Any]], limit: int = 30) -> str:
    for seg in content:
        if seg.get("type") == "text":
            text = str((seg.get("data") or {}).get("text") or "")
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text if len(text) <= limit else text[: limit - 1] + "…"
    return f"[{content[0].get('type', '非文本')}]" if content else "[空]"


def count_nested_forwards(node: ForwardNode) -> int:
    return sum(1 for seg in node.content if seg.get("type") == "forward")


def find_forward_id(segments: Iterable[Any]) -> str | None:
    """在消息段里找合并转发段的 id"""
    for seg in segments:
        if isinstance(seg, Mapping):
            if str(seg.get("type")) == "forward":
                data = seg.get("data") or {}
                if (fid := data.get("id")) is not None:
                    return str(fid)
            continue
        if getattr(seg, "type", "") == "forward":
            data = getattr(seg, "data", None) or {}
            if (fid := data.get("id")) is not None:
                return str(fid)
    return None


def parse_slice(text: str) -> slice:
    """解析 ``[a:b]`` 这样的切片, 允许省略端点与负数"""
    raw = text.strip()
    if raw.startswith("["):
        raw = raw[1:]
    if raw.endswith("]"):
        raw = raw[:-1]
    parts = [piece.strip() for piece in raw.split(":")]
    if len(parts) > 3:
        raise SliceSpecError("切片最多三段: start:stop:step")
    if len(parts) == 1:
        # 只写一个数: 当作 stop, 等价于 [:n]
        parts = ["", parts[0]]
    values: list[int | None] = []
    for piece in parts:
        if piece == "":
            values.append(None)
        else:
            try:
                values.append(int(piece))
            except ValueError as exc:
                raise SliceSpecError(f"「{piece}」不是整数") from exc
    if len(values) == 2:
        values.append(None)
    start, stop, step = values
    if step == 0:
        raise SliceSpecError("步长不能是 0")
    return slice(start, stop, step)

def forward_items(data: object) -> list[Any]:
    """从 get_forward_msg 的 data 里取节点数组, 两种键名都认"""
    if isinstance(data, list):
        return list(data)
    if isinstance(data, Mapping):
        for key in ("messages", "message"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []
