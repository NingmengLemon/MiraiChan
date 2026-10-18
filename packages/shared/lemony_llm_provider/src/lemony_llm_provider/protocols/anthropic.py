"""Anthropic messages 协议"""

from __future__ import annotations

import base64
import json
from typing import Any

from ..errors import LLMConfigError
from ..models import (
    CompletionRequest,
    FinishReason,
    ImagePart,
    Message,
    ReasoningDelta,
    SignatureDelta,
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
    sendable_messages,
    tool_choice_value,
)

_STOP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "tool_use": "tool_calls",
    "refusal": "refusal",
    "pause_turn": "stop",
}


def _content(message: Message) -> str | list[dict[str, Any]]:
    if all(isinstance(part, TextPart) for part in message.parts):
        return message.text()
    out: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            out.append({"type": "text", "text": part.text})
        elif part.url is not None:
            out.append({"type": "image", "source": {"type": "url", "url": part.url}})
        else:
            out.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": base64.b64encode(_data(part)).decode(),
                    },
                }
            )
    return out


def _data(part: ImagePart) -> bytes:
    if part.data is None:
        raise ValueError("ImagePart 需要 url 或 data 之一")
    return part.data


def build(request: CompletionRequest, *, model: str, quirks: Quirks) -> Translation:
    check_capabilities(request, quirks)
    dropped: list[str] = []

    messages: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def flush_results() -> None:
        """anthropic 要求同一轮的多个 tool_result 合并进紧跟其后的那条 user 消息"""
        if pending:
            messages.append({"role": "user", "content": list(pending)})
            pending.clear()

    for message in sendable_messages(request):
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
            messages.append({"role": message.role, "content": _content(message)})
    flush_results()

    max_tokens = request.max_tokens or quirks.anthropic_default_max_tokens
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if request.system:
        body["system"] = request.system
    if request.tools:
        body["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in request.tools
        ]
    choice = tool_choice_value(request.tool_choice, style="anthropic")
    if choice is not None:
        body["tool_choice"] = choice
    if request.json_schema:
        body["output_config"] = {
            "format": {"type": "json_schema", "schema": request.json_schema}
        }
    if request.reasoning:
        effort = request.reasoning.effort
        budget = request.reasoning.budget_tokens
        if quirks.anthropic_thinking_style == "budget":
            if effort == "none":
                body["thinking"] = {"type": "disabled"}
            elif budget:
                if budget < quirks.anthropic_min_budget_tokens:
                    raise LLMConfigError(
                        f"thinking.budget_tokens 至少 {quirks.anthropic_min_budget_tokens}, "
                        f"收到 {budget}"
                    )
                if budget >= max_tokens:
                    raise LLMConfigError(
                        f"thinking.budget_tokens({budget}) 必须小于 max_tokens({max_tokens})"
                    )
                body["thinking"] = {"type": "enabled", "budget_tokens": budget}
            elif effort:
                body["output_config"] = {
                    **body.get("output_config", {}),
                    "effort": quirks.fold_effort(effort),
                }
        elif effort == "none":
            body["thinking"] = {"type": "disabled"}
        else:
            # 新一代模型: thinking.type=adaptive, 强度走 output_config.effort;
            # display 不显式要 summarized 的话拿不到思维链正文
            body["thinking"] = {"type": "adaptive", "display": "summarized"}
            if effort:
                body["output_config"] = {
                    **body.get("output_config", {}),
                    "effort": quirks.fold_effort(effort),
                }
            if budget:
                # adaptive 没有预算这个概念, 只能丢掉
                dropped.append("thinking.budget_tokens")
    # messages.create 已经没有 temperature / top_p / top_k, 传上去只会被拒
    if request.temperature is not None:
        dropped.append("temperature")
    if request.top_p is not None:
        dropped.append("top_p")
    stop = select_stop(request, quirks, dropped)
    if stop:
        body["stop_sequences"] = stop
    body.update(request.extra_body)
    return Translation(body, tuple(dropped))


def parse(obj: Any, acc: StreamAccumulator) -> list[StreamEvent]:
    kind = getattr(obj, "type", "")
    out: list[StreamEvent] = []
    if kind == "message_start":
        usage = obj.message.usage
        # input_tokens 只算未命中缓存的余量, 三者相加才是总输入
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
        block = obj.content_block
        if block.type == "tool_use":
            out.extend(acc.start(obj.index, block.id, block.name))
    elif kind == "content_block_delta":
        delta = obj.delta
        if delta.type == "text_delta":
            out.append(TextDelta(delta.text))
        elif delta.type == "thinking_delta":
            out.append(ReasoningDelta(delta.thinking))
        elif delta.type == "signature_delta":
            acc.signature += delta.signature
            out.append(SignatureDelta(delta.signature))
        elif delta.type == "input_json_delta":
            out.extend(acc.args(obj.index, delta.partial_json))
    elif kind == "message_delta":
        usage = getattr(obj, "usage", None)
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
        acc.finish(_STOP.get(getattr(obj.delta, "stop_reason", None) or "", "other"))
    return out
