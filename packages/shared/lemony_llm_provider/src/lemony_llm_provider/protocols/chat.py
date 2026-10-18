"""OpenAI chat completions 协议"""

from __future__ import annotations

from typing import Any

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
    select_stop,
    select_temperature,
    select_top_p,
    sendable_messages,
    tool_choice_value,
)

_FINISH: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "content_filter",
}


def _content(message: Message) -> str | list[dict[str, Any]]:
    if all(isinstance(part, TextPart) for part in message.parts):
        return message.text()
    out: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            out.append({"type": "text", "text": part.text})
        else:
            out.append({"type": "image_url", "image_url": {"url": part.data_url()}})
    return out


def build(request: CompletionRequest, *, model: str, quirks: Quirks) -> Translation:
    check_capabilities(request, quirks)
    dropped: list[str] = []

    messages: list[dict[str, Any]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    for message in sendable_messages(request):
        if message.role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.text(),
                }
            )
            continue
        if message.tool_calls:
            entry: dict[str, Any] = {
                "role": "assistant",
                "content": _content(message) if message.parts else None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in message.tool_calls
                ],
            }
        else:
            entry = {"role": message.role, "content": _content(message)}
        if message.reasoning:
            # DeepSeek 带 tools 时必须回传, 否则 400
            entry["reasoning_content"] = message.reasoning
        messages.append(entry)

    body: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if quirks.send_include_usage:
        body["stream_options"] = {"include_usage": True}
    if request.tools:
        body["tools"] = [
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
    choice = tool_choice_value(request.tool_choice, style="chat")
    if choice is not None:
        body["tool_choice"] = choice
    if request.json_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.json_schema_name,
                "schema": request.json_schema,
                "strict": True,
            },
        }
    extra: dict[str, Any] = {}
    if request.reasoning and request.reasoning.effort:
        effort = request.reasoning.effort
        if effort == "none":
            if quirks.thinking_off_style == "thinking_param":
                # thinking 不是 SDK 的原生参数, 只能走 extra_body
                extra["thinking"] = {"type": "disabled"}
        else:
            body["reasoning_effort"] = quirks.fold_effort(effort)
    if request.max_tokens is not None:
        body[quirks.max_tokens_field] = request.max_tokens
    temperature = select_temperature(request, quirks, dropped)
    if temperature is not None:
        body["temperature"] = temperature
    top_p = select_top_p(request, quirks, dropped)
    if top_p is not None:
        body["top_p"] = top_p
    stop = select_stop(request, quirks, dropped)
    if stop:
        body["stop"] = stop
    extra.update(request.extra_body)
    return Translation(body, tuple(dropped), extra)


def _usage(raw: Any) -> Usage:
    prompt_details = getattr(raw, "prompt_tokens_details", None)
    completion_details = getattr(raw, "completion_tokens_details", None)
    return Usage(
        input_tokens=getattr(raw, "prompt_tokens", 0) or 0,
        output_tokens=getattr(raw, "completion_tokens", 0) or 0,
        cached_input_tokens=getattr(prompt_details, "cached_tokens", 0) or 0,
        cache_write_input_tokens=getattr(prompt_details, "cache_write_tokens", 0) or 0,
        reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) or 0,
        total_tokens=getattr(raw, "total_tokens", 0) or 0,
    )


def parse(obj: Any, acc: StreamAccumulator) -> list[StreamEvent]:
    out: list[StreamEvent] = []
    if getattr(obj, "usage", None):
        acc.absorb(_usage(obj.usage))
    for choice in obj.choices:
        if getattr(choice, "index", 0) != 0:
            # n > 1 时多条候选会交错进同一条流, 只支持单候选
            continue
        delta = choice.delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            out.append(ReasoningDelta(reasoning))
        content = getattr(delta, "content", None)
        if content:
            out.append(TextDelta(content))
        refusal = getattr(delta, "refusal", None)
        if refusal:
            out.append(TextDelta(refusal))
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
            if function is not None and function.arguments:
                out.extend(acc.args(key, function.arguments))
        if choice.finish_reason:
            acc.finish(_FINISH.get(choice.finish_reason, "other"))
    return out
