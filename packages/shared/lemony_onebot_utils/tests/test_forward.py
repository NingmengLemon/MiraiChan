"""lemony_onebot_utils.forward: 合并转发的构造与发送."""

from __future__ import annotations

from typing import Any

import pytest
from lemony_onebot_utils.forward import (
    ForwardBuilder,
    ForwardTooLargeError,
    Sender,
    split_text,
)
from melobot.protocols.onebot.v11.adapter.segment import ImageSegment, TextSegment

ALICE = Sender(30001, "甲")
BOB = Sender(30002, "乙")


class TestSplitText:
    def test_short_text_is_one_chunk(self):
        assert split_text("hello", 10) == ["hello"]

    def test_empty_text_gives_no_chunks(self):
        assert split_text("", 10) == []
        assert split_text("\n\n", 10) == []

    def test_prefers_line_breaks(self):
        assert split_text("aaaa\nbbbb\ncccc", 10) == ["aaaa\nbbbb", "cccc"]

    def test_hard_cuts_an_overlong_line(self):
        assert split_text("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]

    def test_no_chunk_exceeds_the_limit(self):
        text = "\n".join("y" * n for n in (3, 17, 9, 1, 30, 0, 12))
        chunks = split_text(text, 10)
        assert all(len(c) <= 10 for c in chunks)
        # 只丢掉了换行, 没丢内容
        assert "".join(chunks).replace("\n", "") == text.replace("\n", "")

    def test_rejects_non_positive_limit(self):
        with pytest.raises(ValueError):
            split_text("a", 0)


def _dicts(builder: ForwardBuilder) -> list[dict[str, Any]]:
    return [n.to_dict() for n in builder.build()]


class TestBuilder:
    def test_text_nodes_carry_the_sender(self):
        nodes = _dicts(ForwardBuilder(ALICE).text("hi"))
        assert nodes == [
            {
                "type": "node",
                "data": {
                    "user_id": 30001,
                    "nickname": "甲",
                    "content": [{"type": "text", "data": {"text": "hi"}}],
                },
            }
        ]

    def test_gocq_style_nodes(self):
        data = _dicts(ForwardBuilder(ALICE, use_std=False).text("hi"))[0]["data"]
        assert (data["uin"], data["name"]) == (30001, "甲")

    def test_long_text_is_split_across_nodes(self):
        b = ForwardBuilder(ALICE, max_node_text=4).text("abcdefghij")
        texts = [n["data"]["content"][0]["data"]["text"] for n in _dicts(b)]
        assert texts == ["abcd", "efgh", "ij"]

    def test_per_node_sender_override(self):
        b = ForwardBuilder(ALICE).text("a").text("b", sender=BOB)
        assert [n["data"]["user_id"] for n in _dicts(b)] == [30001, 30002]

    def test_add_keeps_mixed_content_in_one_node(self):
        img = ImageSegment(file="https://example.invalid/a.png")
        b = ForwardBuilder(ALICE).add([TextSegment("看图"), img])
        content = _dicts(b)[0]["data"]["content"]
        assert [s["type"] for s in content] == ["text", "image"]

    def test_add_rejects_empty_content(self):
        with pytest.raises(ValueError):
            ForwardBuilder(ALICE).add([])

    def test_refer_node_has_only_the_id(self):
        assert _dicts(ForwardBuilder(ALICE).refer(123)) == [
            {"type": "node", "data": {"id": "123"}}
        ]

    def test_extend_appends_nodes_in_order(self):
        a = ForwardBuilder(ALICE).text("1")
        b = ForwardBuilder(BOB).text("2")
        assert len(a.extend(b)) == 2

    def test_empty_builder_cannot_build(self):
        with pytest.raises(ValueError):
            ForwardBuilder(ALICE).build()

    def test_too_many_nodes(self):
        b = ForwardBuilder(ALICE, max_nodes=2).texts(["1", "2", "3"])
        with pytest.raises(ForwardTooLargeError):
            b.build()

    def test_missing_sender_outside_event_context(self):
        with pytest.raises(LookupError):
            ForwardBuilder().text("hi")


class _Handle:
    def __init__(self, echo: Any) -> None:
        self._echo = echo

    def __await__(self):
        async def _ret():
            return self._echo

        return _ret().__await__()


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict], dict]] = []

    async def send_forward_custom(self, msgs, user_id=None, group_id=None):
        self.calls.append(
            (
                "custom",
                [m.to_dict() for m in msgs],
                {"user_id": user_id, "group_id": group_id},
            )
        )
        return [_Handle("echo")]


class TestSendTo:
    @pytest.mark.asyncio
    async def test_sends_to_a_group(self):
        adapter = _FakeAdapter()
        echo = await ForwardBuilder(ALICE).text("hi").send_to(adapter, group_id=1)  # ty: ignore[invalid-argument-type]
        assert echo == "echo"
        assert adapter.calls[0][2] == {"user_id": None, "group_id": 1}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", [{}, {"group_id": 1, "user_id": 2}])
    async def test_requires_exactly_one_target(self, target):
        with pytest.raises(ValueError):
            await ForwardBuilder(ALICE).text("hi").send_to(_FakeAdapter(), **target)  # ty: ignore[invalid-argument-type]

    @pytest.mark.asyncio
    async def test_validates_before_sending(self):
        adapter = _FakeAdapter()
        with pytest.raises(ValueError):
            await ForwardBuilder(ALICE).send_to(adapter, user_id=1)  # ty: ignore[invalid-argument-type]
        assert adapter.calls == []
