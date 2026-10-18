"""统一内部模型: 请求、消息、流式事件与用量"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Literal

Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
FinishReason = Literal[
    "stop", "length", "tool_calls", "content_filter", "refusal", "other"
]
Protocol = Literal["chat", "responses", "anthropic"]


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    """图片: 给 url, 或给字节 + media_type"""

    url: str | None = None
    data: bytes | None = None
    media_type: str = "image/png"

    def data_url(self) -> str:
        if self.url is not None:
            return self.url
        if self.data is None:
            raise ValueError("ImagePart 需要 url 或 data 之一")
        b64 = base64.b64encode(self.data).decode()
        return f"data:{self.media_type};base64,{b64}"


Part = TextPart | ImagePart


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON 文本, 保留原文以免精度损失


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    parts: tuple[Part, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # role == "tool" 时指向 ToolCall.id
    # 下面两个是原样带回的字段, 库不加工:
    #   DeepSeek 带 tools 时必须回传 reasoning_content, 否则 400
    #   Anthropic 续接 thinking 时必须回传带 signature 的 thinking 块
    reasoning: str | None = None
    signature: str | None = None
    is_error: bool = False  # role == "tool" 时表示工具执行失败

    @classmethod
    def user(cls, text: str, *images: ImagePart) -> Message:
        return cls("user", (TextPart(text), *images))

    @classmethod
    def assistant(
        cls,
        text: str = "",
        *calls: ToolCall,
        reasoning: str | None = None,
        signature: str | None = None,
    ) -> Message:
        parts = (TextPart(text),) if text else ()
        return cls("assistant", parts, calls, reasoning=reasoning, signature=signature)

    @classmethod
    def tool_result(cls, call_id: str, text: str, *, is_error: bool = False) -> Message:
        return cls("tool", (TextPart(text),), tool_call_id=call_id, is_error=is_error)

    def text(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))

    def is_empty_assistant(self) -> bool:
        """没有正文也没有工具调用的 assistant 消息, 发出去只会让上游报错"""
        return self.role == "assistant" and not self.parts and not self.tool_calls


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class Reasoning:
    effort: Effort | None = None
    budget_tokens: int | None = None


@dataclass(frozen=True)
class CompletionRequest:
    messages: tuple[Message, ...]
    system: str | None = None
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: str | None = None  # auto / none / required / 工具名
    json_schema: dict[str, Any] | None = None
    json_schema_name: str = "output"
    reasoning: Reasoning | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] = ()
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def merged(self, other: Usage) -> Usage:
        """流式里输入与输出分两处到达, 取较大值合并; total 由两部分补齐"""

        def pick(a: int, b: int) -> int:
            return max(a, b)

        input_tokens = pick(self.input_tokens, other.input_tokens)
        output_tokens = pick(self.output_tokens, other.output_tokens)
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=max(
                self.cached_input_tokens, other.cached_input_tokens
            ),
            cache_write_input_tokens=max(
                self.cache_write_input_tokens, other.cache_write_input_tokens
            ),
            reasoning_tokens=max(self.reasoning_tokens, other.reasoning_tokens),
            total_tokens=max(
                self.total_tokens, other.total_tokens, input_tokens + output_tokens
            ),
        )

    def plus(self, other: Usage) -> Usage:
        """累计多个请求的用量; merged 是给流式分片用的, 取的是较大值"""
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            cache_write_input_tokens=(
                self.cache_write_input_tokens + other.cache_write_input_tokens
            ),
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True)
class SignatureDelta:
    signature: str


@dataclass(frozen=True)
class ToolCallStart:
    index: int
    id: str
    name: str


@dataclass(frozen=True)
class ToolCallArgsDelta:
    index: int
    delta: str


@dataclass(frozen=True)
class Completed:
    finish_reason: FinishReason
    tool_calls: tuple[ToolCall, ...]
    usage: Usage | None  # None = 上游没报用量
    endpoint_id: str = ""


StreamEvent = (
    TextDelta
    | ReasoningDelta
    | SignatureDelta
    | ToolCallStart
    | ToolCallArgsDelta
    | Completed
)


@dataclass(frozen=True)
class PartialOutput:
    """流中断时已经下发的部分, 供调用方决定怎么收场"""

    text: str = ""
    reasoning: str = ""
    signature: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage | None = None


class StreamAccumulator:
    """把增量事件拼成完整的 tool_calls / usage / finish_reason, 三条路径共用

    - 工具调用的 index 由这里按出现顺序重编: 各协议的 index 语义不同 (chat 是
      tool_calls 数组下标, responses 是 output item 序号, anthropic 是 content block
      序号), 透传上去调用方没法拼参数。
    - finish_reason 只在收到正常结束标记之后才算数; 没见到标记就收流说明上游被截断。
    """

    def __init__(self) -> None:
        self.usage: Usage | None = None
        self.calls: list[dict[str, str]] = []
        self.finish_reason: FinishReason | None = None
        self.signature = ""
        self.text = ""
        self.reasoning = ""
        self._by_key: dict[Any, int] = {}
        self._reasoning_source: str | None = None

    def absorb(self, usage: Usage) -> None:
        self.usage = usage if self.usage is None else self.usage.merged(usage)

    def accept_reasoning(self, source: str) -> bool:
        """reasoning_text 与 reasoning_summary 同时出现时会重复计数, 只认先来的那种"""
        if self._reasoning_source is None:
            self._reasoning_source = source
        return self._reasoning_source == source

    def observe(self, event: StreamEvent) -> None:
        """记录已经下发的文本, 供中断时交出 partial"""
        if isinstance(event, TextDelta):
            self.text += event.text
        elif isinstance(event, ReasoningDelta):
            self.reasoning += event.text
        elif isinstance(event, SignatureDelta):
            self.signature += event.signature

    def start(self, key: Any, call_id: str, name: str) -> list[StreamEvent]:
        index = self._by_key.get(key)
        if index is not None:
            # 有的实现会在每个分块里重复带 id, 不能重复报"开始"
            slot = self.calls[index]
            slot["id"] = slot["id"] or call_id
            slot["name"] = slot["name"] or name
            return []
        index = len(self.calls)
        self._by_key[key] = index
        self.calls.append({"id": call_id, "name": name, "args": ""})
        return [ToolCallStart(index, call_id, name)]

    def set_name(self, key: Any, name: str) -> None:
        index = self._by_key.get(key)
        if index is not None and not self.calls[index]["name"]:
            self.calls[index]["name"] = name

    def args(self, key: Any, delta: str) -> list[StreamEvent]:
        index = self._by_key.get(key)
        if index is None:
            # 参数比"开始"先到: 先补一个开始, 否则 Completed 里会出现无 id 的假工具调用
            out = self.start(key, "", "")
            if delta:
                out.append(ToolCallArgsDelta(len(self.calls) - 1, delta))
                self.calls[-1]["args"] += delta
            return out
        if delta:
            self.calls[index]["args"] += delta
            return [ToolCallArgsDelta(index, delta)]
        return []

    def fill_args(self, key: Any, arguments: str) -> None:
        """只收到 done 没收到 delta 的兼容层, 用完整参数兜底"""
        index = self._by_key.get(key)
        if index is None:
            self.start(key, "", "")
            index = len(self.calls) - 1
        if not self.calls[index]["args"]:
            self.calls[index]["args"] = arguments

    def finish(self, reason: FinishReason) -> None:
        self.finish_reason = reason

    @property
    def tool_calls(self) -> tuple[ToolCall, ...]:
        return tuple(ToolCall(c["id"], c["name"], c["args"]) for c in self.calls)

    def partial(self) -> PartialOutput:
        return PartialOutput(
            text=self.text,
            reasoning=self.reasoning,
            signature=self.signature,
            tool_calls=self.tool_calls,
            usage=self.usage,
        )

    def completed(self, endpoint_id: str = "") -> Completed:
        from .errors import StreamAborted

        if self.finish_reason is None:
            raise StreamAborted(
                "流在没有结束标记的情况下结束, 不能当成正常完成",
                partial=self.partial(),
            )
        return Completed(self.finish_reason, self.tool_calls, self.usage, endpoint_id)


# 请求侧 effort 折叠: DeepSeek 的取值集合比通用模型窄, 压到 low/high/max 三档
DEEPSEEK_EFFORT: dict[str, str] = {
    "minimal": "low",
    "low": "low",
    "medium": "high",
    "high": "high",
    "xhigh": "high",
    "max": "max",
    "ultra": "max",
}
