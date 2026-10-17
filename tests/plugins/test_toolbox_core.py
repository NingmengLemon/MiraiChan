"""mbplugin_toolbox 的纯函数部分 (不依赖 bot)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from mbplugin_toolbox.core import echo_segments, format_message_data

CARD = {"app": "com.tencent.miniapp", "meta": {"x": 1}}


def test_echo_drops_card_segments_and_copies_data() -> None:
    src = [
        {"type": "text", "data": {"text": "hi"}},
        {"type": "json", "data": {"data": json.dumps(CARD)}},
        {"type": "xml", "data": {"data": "<x/>"}},
        {"type": "image", "data": {"url": "u"}},
        {"type": "face"},
    ]
    out = echo_segments(src)
    assert [s["type"] for s in out] == ["text", "image", "face"]
    assert out[2]["data"] == {}
    out[0]["data"]["text"] = "changed"
    assert src[0]["data"]["text"] == "hi"


def test_format_expands_json_cards_and_drops_raw_message() -> None:
    data = {
        "message_id": 1,
        "raw_message": "[CQ:json,...]",
        "sender": {"user_id": 2, "nickname": "甲"},
        "message": [
            {"type": "json", "data": {"data": json.dumps(CARD)}},
            {"type": "json", "data": {"data": "not json"}},
            {"type": "text", "data": {"text": "中文"}},
        ],
    }
    text = format_message_data(data)
    parsed = json.loads(text)
    assert "raw_message" not in parsed
    assert parsed["sender"]["nickname"] == "甲"
    assert parsed["message"][0]["data"]["data"] == CARD
    assert parsed["message"][1]["data"]["data"] == "not json"
    assert "中文" in text  # 不转义成 \uXXXX
    # 原数据不被修改
    assert isinstance(data["message"][0]["data"]["data"], str)


def test_format_handles_missing_message() -> None:
    assert json.loads(format_message_data({"message_id": 1})) == {
        "message_id": 1,
        "message": [],
    }
