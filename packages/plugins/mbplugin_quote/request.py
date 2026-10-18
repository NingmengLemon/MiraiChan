"""命令参数解析 (纯函数)。

``.mq`` 的参数是空白分隔的 token, 顺序任意:

- ``x..y``: 以被回复消息为 0 的相对闭区间, 端点可以同号, 顺序无关; 只写一个整数
  ``n`` 等价于 ``n..0`` 或 ``0..n`` (即从基准往前或往后取到 n);
- ``-s``: 只取被回复者本人的消息;
- ``Nx``: 输出倍率, 例如 ``2x`` ``1.5x``。

无法识别的 token 报错, 而不是静默忽略。
"""

import re
from dataclasses import dataclass

__all__ = [
    "ChatRequest",
    "LimitExceeded",
    "QuoteRequestError",
    "chat_tokens",
    "check_limits",
    "parse_chat_args",
]

_RANGE_RE = re.compile(r"^([+-]?\d+)\.\.([+-]?\d+)$")
_INT_RE = re.compile(r"^[+-]?\d+$")
# 手机输入法常把 x 打成乘号, 一并接受
_SCALE_RE = re.compile(r"^(\d+(?:\.\d+)?)[xX\u00d7]$")
_SENDER_ONLY_FLAGS = frozenset({"-s", "--sender-only"})


def chat_tokens(text: str, *names: str) -> list[str]:
    """从整条消息里取出命令之后的参数 token。

    melobot 的命令解析器按命令起始符切分参数, 参数里出现的 ``.`` 会被当成下一条命令的
    起点, ``-5..5`` 到手时只剩 ``-5``, 区间的正半段就悄悄丢了。所以这里不经过
    ``CmdArgs``, 直接从原文里切; 遇到下一个命令起始符就停, 免得把后面的命令吃进来。
    """
    pattern = "|".join(re.escape(name) for name in names)
    stripped = re.sub(
        rf"^[.。]\s*(?:{pattern})(?:\s+|$)", "", text.strip(), count=1, flags=re.I
    )
    tokens: list[str] = []
    for token in stripped.split():
        if token[:1] in {".", "。"}:
            break
        tokens.append(token)
    return tokens


class QuoteRequestError(ValueError):
    """参数写法有误, message 直接面向用户"""


class LimitExceeded(QuoteRequestError):
    pass


@dataclass(frozen=True, slots=True)
class ChatRequest:
    start: int = 0
    end: int = 0
    sender_only: bool = False
    scale: float = 1.0

    @property
    def is_single(self) -> bool:
        return self.start == self.end == 0

    @property
    def message_count_upper_bound(self) -> int:
        return self.end - self.start + 1


def parse_chat_args(tokens: list[str]) -> ChatRequest:
    start = end = 0
    range_seen = False
    sender_only = False
    scale: float | None = None
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if token.lower() in _SENDER_ONLY_FLAGS:
            sender_only = True
            continue
        if m := _RANGE_RE.match(token):
            if range_seen:
                raise QuoteRequestError("区间只能写一个")
            a, b = int(m[1]), int(m[2])
            start, end = min(a, b), max(a, b)
            range_seen = True
            continue
        if _INT_RE.match(token):
            if range_seen:
                raise QuoteRequestError("区间只能写一个")
            n = int(token)
            start, end = min(n, 0), max(n, 0)
            range_seen = True
            continue
        if m := _SCALE_RE.match(token):
            if scale is not None:
                raise QuoteRequestError("倍率只能写一个")
            scale = float(m[1])
            if scale <= 0:
                raise QuoteRequestError("倍率必须大于 0")
            continue
        raise QuoteRequestError(
            f"看不懂参数「{token}」, 可用: 区间 x..y (例如 -3..2), 仅本人 -s, 倍率 2x"
        )
    return ChatRequest(
        start=start,
        end=end,
        sender_only=sender_only,
        scale=1.0 if scale is None else scale,
    )


def check_limits(req: ChatRequest, *, max_offset: int, max_scale: float) -> None:
    """超限时抛 LimitExceeded, 豁免者不调用即可"""
    if req.start < -max_offset or req.end > max_offset:
        raise LimitExceeded(f"区间端点需在 -{max_offset}..{max_offset} 之内")
    if req.scale > max_scale:
        raise LimitExceeded(f"倍率不能超过 {max_scale:g}x")
