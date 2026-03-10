from __future__ import annotations

from typing import Any

from melobot.adapter import Echo as RootEcho

from ..const import PROTOCOL_IDENTIFIER


class Echo(RootEcho):
    """Telegram 回应"""

    def __init__(
        self,
        data: Any = None,
        ok: bool = True,
        prompt: str = "",
    ) -> None:
        super().__init__(protocol=PROTOCOL_IDENTIFIER, status=0 if ok else -1)
        self.data = data
        self.ok = ok
        self.prompt = prompt

    def __repr__(self) -> str:
        return f"Echo(ok={self.ok}, data_type={type(self.data).__name__})"

    def result(self) -> Any:
        """获取 Telegram API 返回的结果"""
        if not self.ok:
            raise ValueError(f"Telegram API 调用失败: {self.prompt}")
        return self.data

    def is_ok(self) -> bool:
        return self.ok
