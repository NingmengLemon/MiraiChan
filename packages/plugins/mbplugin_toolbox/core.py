"""管理工具的纯函数部分, 不依赖 bot 上下文, 便于测试。"""

import contextlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["UNECHOABLE_TYPES", "echo_segments", "format_message_data"]

#: 复读时去掉的段: 卡片消息原样发回会被实现端拒绝或变成另一张卡片
UNECHOABLE_TYPES = frozenset({"json", "xml"})


def echo_segments(segments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """复读用的段字典 (type + data), 去掉不能原样发回的段"""
    return [
        {"type": str(s.get("type", "")), "data": dict(s.get("data") or {})}
        for s in segments
        if s.get("type") not in UNECHOABLE_TYPES
    ]


def format_message_data(data: Mapping[str, Any]) -> str:
    """get_msg 返回的 data -> 便于阅读的 JSON 文本。

    去掉与 message 重复的 raw_message; json 段里的卡片内容是字符串化的 JSON, 能解析时展开。
    """
    out = {k: v for k, v in data.items() if k not in ("raw_message", "message")}
    segments: list[dict[str, Any]] = []
    for seg in data.get("message") or []:
        seg_type = seg.get("type")
        seg_data = dict(seg.get("data") or {})
        if seg_type == "json" and isinstance(seg_data.get("data"), str):
            # 解析不了就保持原字符串
            with contextlib.suppress(ValueError):
                seg_data["data"] = json.loads(seg_data["data"])
        segments.append({"type": seg_type, "data": seg_data})
    out["message"] = segments
    return json.dumps(out, indent=2, ensure_ascii=False)
