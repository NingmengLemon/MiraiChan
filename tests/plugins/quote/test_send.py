"""引用图发送结果的判定."""

from __future__ import annotations

from typing import Any

import pytest
from mbplugin_quote.send import echo_message_id


class _Echo:
    def __init__(self, ok: bool, data: Any = None) -> None:
        self._ok = ok
        self.data = data

    def is_ok(self) -> bool:
        return self._ok


@pytest.mark.parametrize(
    ("echo", "expected"),
    [
        (_Echo(True, {"message_id": 123}), "123"),
        (_Echo(True, {"message_id": "456"}), "456"),
        (_Echo(False, {"message_id": 123}), None),
        (_Echo(True, None), None),
        (_Echo(True, {}), None),
        (None, None),
    ],
)
def test_echo_message_id(echo: Any, expected: str | None) -> None:
    assert echo_message_id(echo) == expected
