"""OpenAI responses 协议"""

from __future__ import annotations

from typing import Any

from ..errors import StreamAborted
from ..models import (
    CompletionRequest,
    FinishReason,
    Message,
    ReasoningDelta,
    StreamAccumulator,
    StreamEvent,
    TextDelta,
    TextPart,
    Usage,
)
from ..quirks import Quirks
from .base import (
    Translation,
    check_capabilities,
    select_temperature,
    select_top_p,
    sendable_messages,
    tool_choice_value,
)

_INCOMPLETE: dict[str, FinishReason] = {
    "max_output_tokens": "length",
    "content_filter": "content_filter",
}


def _content(message: Message) -> str | list[dict[str, Any]]:
    if all(isinstance(part, TextPart) for part in message.parts):
        return message.text()
    out: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            out.append({"type": "input_text", "text": part.text})
        else:
            out.append({"type": "input_image", "image_url": part.data_url()})
    return out


def build(request: CompletionRequest, *, model: str, quirks: Quirks) -> Translation:
    check_capabilities(request, quirks)
    dropped: list[str] = []

    items: list[dict[str, Any]] = []
    for message in sendable_messages(request):
        if message.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.text(),
                }
            )
            continue
        if message.tool_calls:
            if message.parts:
                items.append({"role": "assistant", "content": _content(message)})
            items.extend(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in message.tool_calls
            )
            continue
        items.append({"role": message.role, "content": _content(message)})

    body: dict[str, Any] = {"model": model, "input": items, "stream": True}
    if request.system:
        body["instructions"] = request.system
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in request.tools
        ]
    choice = tool_choice_value(request.tool_choice, style="responses")
    if choice is not None:
        body["tool_choice"] = choice
    if request.json_schema:
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": request.json_schema_name,
                "schema": request.json_schema,
                "strict": True,
            }
        }
    if request.reasoning and request.reasoning.effort:
        body["reasoning"] = {"effort": quirks.fold_effort(request.reasoning.effort)}
    if request.max_tokens is not None:
        body["max_output_tokens"] = request.max_tokens
    temperature = select_temperature(request, quirks, dropped)
    if temperature is not None:
        body["temperature"] = temperature
    top_p = select_top_p(request, quirks, dropped)
    if top_p is not None:
        body["top_p"] = top_p
    if request.stop:
        # responses 协议本身没有 stop 参数
        dropped.append("stop")
    body.update(request.extra_body)
    return Translation(body, tuple(dropped))


def _usage(raw: Any) -> Usage:
    input_details = getattr(raw, "input_tokens_details", None)
    output_details = getattr(raw, "output_tokens_details", None)
    return Usage(
        input_tokens=getattr(raw, "input_tokens", 0) or 0,
        output_tokens=getattr(raw, "output_tokens", 0) or 0,
        cached_input_tokens=getattr(input_details, "cached_tokens", 0) or 0,
        cache_write_input_tokens=getattr(input_details, "cache_write_tokens", 0) or 0,
        reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0,
        total_tokens=getattr(raw, "total_tokens", 0) or 0,
    )


def _absorb(acc: StreamAccumulator, raw: Any) -> None:
    if raw is not None:
        acc.absorb(_usage(raw))


def parse(obj: Any, acc: StreamAccumulator) -> list[StreamEvent]:
    kind = getattr(obj, "type", "")
    out: list[StreamEvent] = []
    if kind == "response.reasoning_text.delta":
        if acc.accept_reasoning("text"):
            out.append(ReasoningDelta(obj.delta))
    elif kind == "response.reasoning_summary_text.delta":
        if acc.accept_reasoning("summary"):
            out.append(ReasoningDelta(obj.delta))
    elif kind == "response.output_text.delta" or kind == "response.refusal.delta":
        out.append(TextDelta(obj.delta))
    elif kind == "response.output_item.added":
        item = obj.item
        if item.type == "function_call":
            # 这个事件上没有 item_id, 统一用 output_index 作 key
            out.extend(acc.start(obj.output_index, item.call_id, item.name))
    elif kind == "response.function_call_arguments.delta":
        out.extend(acc.args(obj.output_index, obj.delta))
    elif kind == "response.function_call_arguments.done":
        acc.fill_args(obj.output_index, obj.arguments)
    elif kind == "response.output_item.done":
        item = obj.item
        if item.type == "function_call":
            acc.fill_args(obj.output_index, item.arguments)
    elif kind == "response.completed":
        response = obj.response
        _absorb(acc, response.usage)
        if response.status == "incomplete":
            detail = getattr(response.incomplete_details, "reason", None)
            acc.finish(_INCOMPLETE.get(detail or "", "other"))
        else:
            acc.finish("tool_calls" if acc.calls else "stop")
    elif kind == "response.incomplete":
        response = obj.response
        _absorb(acc, response.usage)
        detail = getattr(response.incomplete_details, "reason", None)
        acc.finish(_INCOMPLETE.get(detail or "", "other"))
    elif kind == "response.failed":
        error = getattr(obj.response, "error", None)
        code = getattr(error, "code", None) or "response.failed"
        message = getattr(error, "message", None) or "上游返回 response.failed"
        raise StreamAborted(f"{code}: {message}", partial=acc.partial())
    elif kind == "error":
        raise StreamAborted(
            f"{getattr(obj, 'code', None) or 'error'}: {obj.message}",
            partial=acc.partial(),
        )
    return out
