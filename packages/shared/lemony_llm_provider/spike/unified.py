"""三套协议归一化的原型 (后续搬进 lemony_llm_provider 正身)

统一模型: Message / TextPart / ImagePart / ToolCall / ToolSpec
    CompletionRequest -> 三套协议的请求体 (to_*)
    各协议的流式事件 -> StreamEvent 序列 (from_*)
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Literal

Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
FinishReason = Literal[
    "stop", "length", "tool_calls", "content_filter", "refusal", "other"
]


class SpikeError(Exception):
    """原型里的错误基类, 正式实现会换成 LLMError 层级"""


class SpikeApiError(SpikeError):
    """服务端在流里明确报错"""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(f"{code}: {message}" if code else message)
        self.code = code


class SpikeTruncated(SpikeError):
    """流在没有结束标记的情况下断了, 不能当成正常结束"""


# --------------------------------------------------------------------------
# 统一模型
# --------------------------------------------------------------------------


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
        assert self.data is not None
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
    # 下面两个是"原样带回"的字段, 库不加工:
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


# --------------------------------------------------------------------------
# 归一化后的流式事件
# --------------------------------------------------------------------------


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


StreamEvent = (
    TextDelta
    | ReasoningDelta
    | SignatureDelta
    | ToolCallStart
    | ToolCallArgsDelta
    | Completed
)


# 请求侧 effort 折叠: 各家的取值集合不一样, 先压到 low/high/max 三档
_EFFORT_FOLD: dict[str, str] = {
    "minimal": "low",
    "low": "low",
    "medium": "high",
    "high": "high",
    "xhigh": "high",
    "max": "max",
    "ultra": "max",
}


def fold_effort(effort: Effort) -> str:
    return _EFFORT_FOLD[effort]


@dataclass(frozen=True)
class Translation:
    body: dict[str, Any]
    dropped: tuple[str, ...]  # 协议不支持而被丢弃的参数, 正式实现里要记日志


def _messages(request: CompletionRequest) -> list[Message]:
    return [m for m in request.messages if not m.is_empty_assistant()]


# --------------------------------------------------------------------------
# 请求侧: 统一模型 -> 三套协议
# --------------------------------------------------------------------------


def _chat_content(message: Message) -> str | list[dict[str, Any]]:
    if all(isinstance(p, TextPart) for p in message.parts):
        return message.text()
    out: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            out.append({"type": "text", "text": part.text})
        else:
            out.append({"type": "image_url", "image_url": {"url": part.data_url()}})
    return out


def to_chat(
    request: CompletionRequest, *, model: str, max_tokens_field: str = "max_tokens"
) -> Translation:
    messages: list[dict[str, Any]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    for message in _messages(request):
        if message.role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.text(),
                }
            )
        elif message.tool_calls:
            body: dict[str, Any] = {
                "role": "assistant",
                "content": _chat_content(message) if message.parts else None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in message.tool_calls
                ],
            }
            if message.reasoning:
                # DeepSeek 带 tools 时必须回传, 否则 400
                body["reasoning_content"] = message.reasoning
            messages.append(body)
        else:
            body = {"role": message.role, "content": _chat_content(message)}
            if message.reasoning:
                body["reasoning_content"] = message.reasoning
            messages.append(body)

    out: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    out["stream_options"] = {"include_usage": True}
    if request.tools:
        out["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in request.tools
        ]
    if request.tool_choice:
        out["tool_choice"] = (
            request.tool_choice
            if request.tool_choice in {"auto", "none", "required"}
            else {"type": "function", "function": {"name": request.tool_choice}}
        )
    if request.json_schema:
        out["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.json_schema_name,
                "schema": request.json_schema,
                "strict": True,
            },
        }
    if request.reasoning and request.reasoning.effort:
        if request.reasoning.effort == "none":
            # DeepSeek 的 chat 侧开关走 thinking, 不是 reasoning_effort
            out["thinking"] = {"type": "disabled"}
        else:
            out["reasoning_effort"] = fold_effort(request.reasoning.effort)
    if request.max_tokens is not None:
        out[max_tokens_field] = request.max_tokens
    if request.temperature is not None:
        out["temperature"] = request.temperature
    if request.top_p is not None:
        out["top_p"] = request.top_p
    if request.stop:
        out["stop"] = list(request.stop)
    out.update(request.extra_body)
    return Translation(out, ())


def to_responses(request: CompletionRequest, *, model: str) -> Translation:
    items: list[dict[str, Any]] = []
    for message in _messages(request):
        if message.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.text(),
                }
            )
        elif message.tool_calls:
            if message.parts:
                items.append(
                    {"role": "assistant", "content": _responses_content(message)}
                )
            items.extend(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in message.tool_calls
            )
        else:
            items.append({"role": message.role, "content": _responses_content(message)})

    out: dict[str, Any] = {"model": model, "input": items, "stream": True}
    if request.system:
        out["instructions"] = request.system
    if request.tools:
        out["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in request.tools
        ]
    if request.tool_choice:
        out["tool_choice"] = (
            request.tool_choice
            if request.tool_choice in {"auto", "none", "required"}
            else {"type": "function", "name": request.tool_choice}
        )
    if request.json_schema:
        out["text"] = {
            "format": {
                "type": "json_schema",
                "name": request.json_schema_name,
                "schema": request.json_schema,
                "strict": True,
            }
        }
    if request.reasoning and request.reasoning.effort:
        out["reasoning"] = {"effort": request.reasoning.effort}
    if request.max_tokens is not None:
        out["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        out["temperature"] = request.temperature
    if request.top_p is not None:
        out["top_p"] = request.top_p
    out.update(request.extra_body)
    dropped = ("stop",) if request.stop else ()
    return Translation(out, dropped)


def _responses_content(message: Message) -> str | list[dict[str, Any]]:
    if all(isinstance(p, TextPart) for p in message.parts):
        return message.text()
    out: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            out.append({"type": "input_text", "text": part.text})
        else:
            out.append({"type": "input_image", "image_url": part.data_url()})
    return out


def to_anthropic(request: CompletionRequest, *, model: str) -> Translation:
    messages: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def flush_results() -> None:
        """anthropic 要求同一轮的多个 tool_result 合并进紧跟其后的那条 user 消息"""
        if pending:
            messages.append({"role": "user", "content": list(pending)})
            pending.clear()

    for message in _messages(request):
        if message.role == "tool":
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.text(),
            }
            if message.is_error:
                block["is_error"] = True
            pending.append(block)
            continue
        flush_results()
        if message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.reasoning and message.signature:
                # thinking 块必须排在正文与工具调用之前, 且原样带回 signature
                blocks.append(
                    {
                        "type": "thinking",
                        "thinking": message.reasoning,
                        "signature": message.signature,
                    }
                )
            if message.text():
                blocks.append({"type": "text", "text": message.text()})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": json.loads(call.arguments or "{}"),
                }
                for call in message.tool_calls
            )
            messages.append({"role": "assistant", "content": blocks})
        else:
            messages.append(
                {"role": message.role, "content": _anthropic_content(message)}
            )
    flush_results()

    max_tokens = request.max_tokens or 2048
    out: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if request.system:
        out["system"] = request.system
    if request.tools:
        out["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in request.tools
        ]
    if request.tool_choice:
        out["tool_choice"] = (
            {"type": "auto"}
            if request.tool_choice == "auto"
            else {"type": "any"}
            if request.tool_choice == "required"
            else {"type": "none"}
            if request.tool_choice == "none"
            else {"type": "tool", "name": request.tool_choice}
        )
    if request.json_schema:
        out["output_config"] = {
            "format": {"type": "json_schema", "schema": request.json_schema}
        }
    if request.reasoning:
        if request.reasoning.effort == "none":
            out["thinking"] = {"type": "disabled"}
        elif request.reasoning.budget_tokens:
            out["thinking"] = {
                "type": "enabled",
                "budget_tokens": request.reasoning.budget_tokens,
            }
        elif request.reasoning.effort:
            out["output_config"] = {
                **out.get("output_config", {}),
                "effort": fold_effort(request.reasoning.effort),
            }
    if request.stop:
        out["stop_sequences"] = list(request.stop)
    out.update(request.extra_body)
    dropped = tuple(
        name for name in ("temperature", "top_p") if getattr(request, name) is not None
    )
    return Translation(_validated_anthropic(out, request), dropped)


def _validated_anthropic(
    body: dict[str, Any], request: CompletionRequest
) -> dict[str, Any]:
    """anthropic 对 thinking 与 max_tokens 的关系有硬要求, 提前拦下"""
    thinking = body.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        budget = thinking.get("budget_tokens", 0)
        if budget < 1024:
            raise ValueError(f"thinking.budget_tokens 至少 1024, 收到 {budget}")
        if budget >= body["max_tokens"]:
            raise ValueError(
                f"thinking.budget_tokens({budget}) 必须小于 max_tokens({body['max_tokens']})"
            )
    return body


def _anthropic_content(message: Message) -> str | list[dict[str, Any]]:
    if all(isinstance(p, TextPart) for p in message.parts):
        return message.text()
    out: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            out.append({"type": "text", "text": part.text})
        elif part.url is not None:
            out.append({"type": "image", "source": {"type": "url", "url": part.url}})
        else:
            assert part.data is not None
            out.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": base64.b64encode(part.data).decode(),
                    },
                }
            )
    return out


# --------------------------------------------------------------------------
# 响应侧: 三套协议 -> 归一化事件
# --------------------------------------------------------------------------

_CHAT_FINISH: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "content_filter",
}

_RESPONSES_INCOMPLETE: dict[str, FinishReason] = {
    "max_output_tokens": "length",
    "content_filter": "content_filter",
}

_ANTHROPIC_STOP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "tool_use": "tool_calls",
    "refusal": "refusal",
    "pause_turn": "stop",
}


class Accumulator:
    """把增量事件拼成完整的 tool_calls / usage / finish_reason, 三条路径共用

    - 工具调用的 index 由这里按出现顺序重编: 各协议的 index 语义不同 (chat 是
      tool_calls 数组下标, responses 是 output item 序号, anthropic 是 content block 序号)。
    - finish_reason 与 usage 只有在收到结束标记之后才算数, 没见到标记就收流说明
      上游被截断, 不能当成正常结束。
    """

    def __init__(self) -> None:
        self.usage: Usage | None = None
        self.calls: list[dict[str, str]] = []
        self.finish_reason: FinishReason | None = None
        self.signature = ""
        self._by_key: dict[Any, int] = {}
        self._reasoning_source: str | None = None

    # -- 用量 --------------------------------------------------------------
    def absorb(self, usage: Usage) -> None:
        self.usage = usage if self.usage is None else self.usage.merged(usage)

    # -- 思维链来源去重 ----------------------------------------------------
    def accept_reasoning(self, source: str) -> bool:
        """reasoning_text 与 reasoning_summary 同时出现时会重复计数, 只认先来的那种"""
        if self._reasoning_source is None:
            self._reasoning_source = source
        return self._reasoning_source == source

    # -- 工具调用 ----------------------------------------------------------
    def _slot(self, key: Any) -> int | None:
        return self._by_key.get(key)

    def start(self, key: Any, call_id: str, name: str) -> list[StreamEvent]:
        index = self._slot(key)
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
        index = self._slot(key)
        if index is not None and not self.calls[index]["name"]:
            self.calls[index]["name"] = name

    def args(self, key: Any, delta: str) -> list[StreamEvent]:
        index = self._slot(key)
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
        index = self._slot(key)
        if index is None:
            self.start(key, "", "")
            index = len(self.calls) - 1
        if not self.calls[index]["args"]:
            self.calls[index]["args"] = arguments

    # -- 收尾 --------------------------------------------------------------
    def finish(self, reason: FinishReason) -> None:
        self.finish_reason = reason

    def completed(self) -> Completed:
        if self.finish_reason is None:
            raise SpikeTruncated("流在没有结束标记的情况下结束, 不能当成正常完成")
        calls = tuple(ToolCall(c["id"], c["name"], c["args"]) for c in self.calls)
        return Completed(self.finish_reason, calls, self.usage)


def from_chat_chunk(chunk: Any, acc: Accumulator) -> list[StreamEvent]:
    """openai ChatCompletionChunk -> 事件 (含 DeepSeek 的 reasoning_content)"""
    out: list[StreamEvent] = []
    if getattr(chunk, "usage", None):
        acc.absorb(_chat_usage(chunk.usage))
    for choice in chunk.choices:
        if getattr(choice, "index", 0) != 0:
            # n > 1 时多条候选会交错进同一条流, 原型只支持单候选
            continue
        delta = choice.delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            out.append(ReasoningDelta(reasoning))
        if getattr(delta, "content", None):
            out.append(TextDelta(delta.content))
        if getattr(delta, "refusal", None):
            # 拒答内容走同一个文本通道, 停止原因由 finish_reason 决定
            out.append(TextDelta(delta.refusal))
        legacy = getattr(delta, "function_call", None)
        if legacy is not None:
            out.extend(acc.start(0, "", legacy.name or ""))
            out.extend(acc.args(0, legacy.arguments or ""))
        for call in getattr(delta, "tool_calls", None) or []:
            key = getattr(call, "index", 0)
            function = getattr(call, "function", None)
            name = getattr(function, "name", None)
            if call.id or name:
                out.extend(acc.start(key, call.id or "", name or ""))
            elif name:
                acc.set_name(key, name)
            if function is not None and function.arguments:
                out.extend(acc.args(key, function.arguments))
        if choice.finish_reason:
            acc.finish(_CHAT_FINISH.get(choice.finish_reason, "other"))
    return out


def _chat_usage(usage: Any) -> Usage:
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    return Usage(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        cached_input_tokens=getattr(prompt_details, "cached_tokens", 0) or 0,
        cache_write_input_tokens=getattr(prompt_details, "cache_write_tokens", 0) or 0,
        reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )


def from_responses_event(event: Any, acc: Accumulator) -> list[StreamEvent]:
    kind = getattr(event, "type", "")
    out: list[StreamEvent] = []
    if kind == "response.reasoning_text.delta":
        if acc.accept_reasoning("text"):
            out.append(ReasoningDelta(event.delta))
    elif kind == "response.reasoning_summary_text.delta":
        if acc.accept_reasoning("summary"):
            out.append(ReasoningDelta(event.delta))
    elif kind == "response.output_text.delta" or kind == "response.refusal.delta":
        out.append(TextDelta(event.delta))
    elif kind == "response.output_item.added":
        item = event.item
        if item.type == "function_call":
            # item_id 在这个事件上不存在, 统一用 output_index 作 key
            out.extend(acc.start(event.output_index, item.call_id, item.name))
    elif kind == "response.function_call_arguments.delta":
        out.extend(acc.args(event.output_index, event.delta))
    elif kind == "response.function_call_arguments.done":
        acc.fill_args(event.output_index, event.arguments)
    elif kind == "response.output_item.done":
        item = event.item
        if item.type == "function_call":
            acc.fill_args(event.output_index, item.arguments)
    elif kind == "response.completed":
        response = event.response
        _absorb_responses_usage(acc, response.usage)
        if response.status == "incomplete":
            detail = getattr(response.incomplete_details, "reason", None)
            acc.finish(_RESPONSES_INCOMPLETE.get(detail or "", "other"))
        else:
            acc.finish("tool_calls" if acc.calls else "stop")
    elif kind == "response.incomplete":
        response = event.response
        _absorb_responses_usage(acc, response.usage)
        detail = getattr(response.incomplete_details, "reason", None)
        acc.finish(_RESPONSES_INCOMPLETE.get(detail or "", "other"))
    elif kind == "response.failed":
        error = getattr(event.response, "error", None)
        raise SpikeApiError(
            getattr(error, "message", "response.failed"),
            code=getattr(error, "code", None),
        )
    elif kind == "error":
        raise SpikeApiError(event.message, code=getattr(event, "code", None))
    return out


def _absorb_responses_usage(acc: Accumulator, usage: Any) -> None:
    if usage is None:
        return
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    acc.absorb(
        Usage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cached_input_tokens=getattr(input_details, "cached_tokens", 0) or 0,
            cache_write_input_tokens=getattr(input_details, "cache_write_tokens", 0)
            or 0,
            reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )
    )


def from_anthropic_event(event: Any, acc: Accumulator) -> list[StreamEvent]:
    kind = getattr(event, "type", "")
    out: list[StreamEvent] = []
    if kind == "message_start":
        usage = event.message.usage
        # anthropic 的 input_tokens 只算未命中缓存的余量, 三者相加才是总输入
        read = usage.cache_read_input_tokens or 0
        write = usage.cache_creation_input_tokens or 0
        acc.absorb(
            Usage(
                input_tokens=usage.input_tokens + read + write,
                output_tokens=usage.output_tokens,
                cached_input_tokens=read,
                cache_write_input_tokens=write,
            )
        )
    elif kind == "content_block_start":
        block = event.content_block
        if block.type == "tool_use":
            out.extend(acc.start(event.index, block.id, block.name))
    elif kind == "content_block_delta":
        delta = event.delta
        if delta.type == "text_delta":
            out.append(TextDelta(delta.text))
        elif delta.type == "thinking_delta":
            out.append(ReasoningDelta(delta.thinking))
        elif delta.type == "signature_delta":
            acc.signature += delta.signature
            out.append(SignatureDelta(delta.signature))
        elif delta.type == "input_json_delta":
            out.extend(acc.args(event.index, delta.partial_json))
    elif kind == "message_delta":
        usage = getattr(event, "usage", None)
        if usage is not None:
            acc.absorb(
                Usage(
                    output_tokens=usage.output_tokens or 0,
                    reasoning_tokens=getattr(
                        getattr(usage, "output_tokens_details", None),
                        "thinking_tokens",
                        0,
                    )
                    or 0,
                )
            )
        stop = getattr(event.delta, "stop_reason", None)
        acc.finish(_ANTHROPIC_STOP.get(stop or "", "other"))
    return out
