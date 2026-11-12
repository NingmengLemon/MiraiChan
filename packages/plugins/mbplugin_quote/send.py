"""发送结果判定: 只有成功的 echo 才带可用的消息 id."""

from __future__ import annotations

from typing import Any


def echo_message_id(echo: Any) -> str | None:
    """从 send_msg 的 echo 取消息 id; 失败、缺 data 或缺 id 时返回 None."""
    if echo is None or not echo.is_ok():
        return None
    data = getattr(echo, "data", None)
    if not isinstance(data, dict):
        return None
    message_id = data.get("message_id")
    return None if message_id is None else str(message_id)
