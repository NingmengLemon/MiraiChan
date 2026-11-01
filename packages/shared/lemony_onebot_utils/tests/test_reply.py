"""回复段提取的回归测试."""

from __future__ import annotations

from typing import Any, cast

import pytest
from lemony_onebot_utils.botutils import reply_message_id


class _Segment:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class _Event:
    def __init__(self, replies: list[_Segment]) -> None:
        self._replies = replies

    def get_segments(self, _type: object) -> list[_Segment]:
        return self._replies


@pytest.mark.parametrize(
    ("replies", "expected"),
    [
        ([_Segment({"id": 123})], 123),
        ([_Segment({"id": "456"})], 456),
        ([], None),
        ([_Segment({})], None),
        ([_Segment({"id": "not-a-number"})], None),
    ],
)
def test_reply_message_id(replies: list[_Segment], expected: int | None) -> None:
    event = cast(Any, _Event(replies))
    assert reply_message_id(event) == expected
