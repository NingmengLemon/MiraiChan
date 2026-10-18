"""转发缩水: 切片解析、节点归一化与整条流水线

IO 用假实现, 不连协议端。
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from mbplugin_forward_strip.nodes import (
    ForwardNode,
    SliceSpecError,
    count_nested_forwards,
    find_forward_id,
    from_payload,
    parse_slice,
    to_payload,
)
from mbplugin_forward_strip.pipeline import StripError, strip_forward


def _std_node(uin: int, name: str, text: str) -> dict[str, Any]:
    return {
        "type": "node",
        "data": {
            "user_id": uin,
            "nickname": name,
            "content": [{"type": "text", "data": {"text": text}}],
        },
    }


def _gocq_node(uin: int, name: str, text: str, time: int = 0) -> dict[str, Any]:
    return {
        "type": "node",
        "data": {
            "uin": uin,
            "name": name,
            "time": time,
            "content": [{"type": "text", "data": {"text": text}}],
        },
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[1:]", slice(1, None)),
        ("[:-3]", slice(None, -3)),
        ("-3:", slice(-3, None)),
        ("2", slice(None, 2)),
        ("[1:3]", slice(1, 3)),
        ("[1:5:2]", slice(1, 5, 2)),
        ("[:]", slice(None, None)),
    ],
)
def test_parse_slice(text: str, expected: slice) -> None:
    assert parse_slice(text) == expected


@pytest.mark.parametrize("text", ["a", "1:2:3:4", "1::0", "[1:x]"])
def test_parse_slice_rejects(text: str) -> None:
    with pytest.raises(SliceSpecError):
        parse_slice(text)


def test_from_payload_both_shapes() -> None:
    std = from_payload(_std_node(10001, "阿岚", "在吗"))
    assert std is not None
    assert (std.uin, std.name) == (10001, "阿岚")
    assert std.content[0]["data"]["text"] == "在吗"

    gocq = from_payload(_gocq_node(10002, "小满", "在", time=1700000000))
    assert gocq is not None
    assert (gocq.uin, gocq.name, gocq.time) == (10002, "小满", 1700000000)


def test_refer_and_text_content() -> None:
    refer = from_payload({"type": "node", "data": {"id": "abc"}})
    assert refer is not None and refer.is_refer and refer.refer_id == "abc"
    text_content = from_payload(
        {"type": "node", "data": {"uin": 1, "name": "某人", "content": "纯文本"}}
    )
    assert text_content is not None
    assert text_content.content == ({"type": "text", "data": {"text": "纯文本"}},)


def test_to_payload_keeps_identity() -> None:
    node = from_payload(_gocq_node(10003, "阿岚", "看图", time=1700000001))
    assert node is not None
    payload = to_payload(node)
    data = payload["data"]
    assert (data["uin"], data["name"], data["time"]) == (10003, "阿岚", 1700000001)
    # 再解析一次是完全一样的节点
    assert from_payload(payload) == node


def test_find_forward_id_accepts_objects() -> None:
    class _Seg:
        type = "forward"
        data: ClassVar[dict[str, Any]] = {"id": 12345}

    assert find_forward_id([{"type": "text", "data": {"text": "x"}}, _Seg()]) == "12345"
    assert find_forward_id([{"type": "text", "data": {"text": "x"}}]) is None


def test_count_nested() -> None:
    node = ForwardNode(
        content=(
            {"type": "text", "data": {"text": "看这个"}},
            {"type": "forward", "data": {"id": "inner"}},
        ),
        uin=1,
        name="某人",
    )
    assert count_nested_forwards(node) == 1


class _FakeIo:
    def __init__(
        self, segments: Sequence[Any], nodes: Sequence[Any], *, fail_first: bool = False
    ) -> None:
        self.segments = list(segments)
        self.nodes = list(nodes)
        self.fail_first = fail_first
        self.sent: list[list[dict[str, Any]]] = []

    async def get_message_segments(self, message_id: int) -> Sequence[Any]:
        assert message_id == 999
        return self.segments

    async def get_forward_nodes(self, forward_id: str) -> Sequence[Any]:
        assert forward_id == "fw-1"
        return self.nodes

    async def send_forward_nodes(
        self, group_id: int, nodes: Sequence[dict[str, Any]]
    ) -> None:
        assert group_id == 20000
        if self.fail_first and not self.sent:
            self.sent.append(list(nodes))
            raise RuntimeError("协议端拒收嵌套转发")
        self.sent.append(list(nodes))


def _reply_segments() -> list[dict[str, Any]]:
    return [{"type": "forward", "data": {"id": "fw-1"}}]


@pytest.mark.asyncio
async def test_strip_keeps_identity_and_order() -> None:
    nodes = [_gocq_node(10000 + i, f"人{i}", f"第{i}条") for i in range(5)]
    io = _FakeIo(_reply_segments(), nodes)
    result = await strip_forward(io, group_id=20000, reply_message_id=999, spec="[:-2]")
    assert (result.total, result.kept, result.nested) == (5, 3, 0)
    sent = io.sent[0]
    assert [n["data"]["name"] for n in sent] == ["人0", "人1", "人2"]
    assert [n["data"]["uin"] for n in sent] == [10000, 10001, 10002]
    assert sent[0]["data"]["content"][0]["data"]["text"] == "第0条"


@pytest.mark.asyncio
async def test_strip_refuses_to_degrade_nested_forward() -> None:
    # 带嵌套转发时如果发送失败, 宁可报错, 也不发出缺内容的记录
    nodes = [
        _gocq_node(1, "甲", "普通"),
        {
            "type": "node",
            "data": {
                "uin": 2,
                "name": "乙",
                "content": [
                    {"type": "text", "data": {"text": "还有一层"}},
                    {"type": "forward", "data": {"id": "inner"}},
                ],
            },
        },
    ]
    io = _FakeIo(_reply_segments(), nodes, fail_first=True)
    with pytest.raises(StripError, match="嵌套转发"):
        await strip_forward(io, group_id=20000, reply_message_id=999, spec="[:]")
    # 只尝试过一次, 没有发出残缺的版本
    assert len(io.sent) == 1


@pytest.mark.asyncio
async def test_strip_plain_failure_is_generic() -> None:
    io = _FakeIo(_reply_segments(), [_gocq_node(1, "甲", "一")], fail_first=True)
    with pytest.raises(StripError, match="没有发出去"):
        await strip_forward(io, group_id=20000, reply_message_id=999, spec="[:]")


@pytest.mark.asyncio
async def test_strip_errors() -> None:
    io = _FakeIo([{"type": "text", "data": {"text": "普通消息"}}], [])
    with pytest.raises(StripError, match="没有合并转发"):
        await strip_forward(io, group_id=20000, reply_message_id=999, spec="[:]")

    io = _FakeIo(_reply_segments(), [_gocq_node(1, "甲", "一")])
    with pytest.raises(StripError, match="一条都不剩"):
        await strip_forward(io, group_id=20000, reply_message_id=999, spec="[5:]")

    io = _FakeIo(
        _reply_segments(), [_gocq_node(1, "甲", "一"), _gocq_node(2, "乙", "二")]
    )
    with pytest.raises(StripError, match="上限"):
        await strip_forward(
            io, group_id=20000, reply_message_id=999, spec="[:]", max_nodes=1
        )
