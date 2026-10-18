"""Gemini 原生协议 (models.generateContent / streamGenerateContent)

与另外三条协议不同, 这一条直接构造官方 SDK 的类型对象, 由调用方把 ``contents`` 与
``config`` 展开进 ``client.aio.models.generate_content*``。

几个这一代模型才有的硬性要求:

- 回传工具调用时必须带上它自己的 ``thought_signature``, 否则上游直接 400;
- 没有 ``tool`` 角色, 函数结果放在 user 回合里的 ``function_response`` part;
- 思考过程只下发签名, 正文为空, 用量里的 ``thoughts_token_count`` 单独计。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from google.genai import types

from ..errors import LLMConfigError
from ..models import (
    CompletionRequest,
    FinishReason,
    ImagePart,
    Message,
    Reasoning,
    ReasoningDelta,
    SignatureDelta,
    StreamAccumulator,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
)
from ..quirks import Quirks
from .base import Translation, check_capabilities, tool_choice_value

__all__ = ["build", "parse"]

#: effort -> thinking_level
_EFFORT_LEVEL = {
    "minimal": "MINIMAL",
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "xhigh": "HIGH",
    "max": "HIGH",
    "ultra": "HIGH",
}

_FINISH: dict[str, FinishReason] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "MALFORMED_FUNCTION_CALL": "other",
    "IMAGE_SAFETY": "content_filter",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "LANGUAGE": "content_filter",
    "OTHER": "other",
}


def _b64(data: bytes | None) -> str | None:
    return base64.b64encode(data).decode() if data else None


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode())


def _schema(node: Mapping[str, Any]) -> types.Schema:
    """把 JSON Schema 子集翻成 SDK 的 Schema"""
    type_name = str(node.get("type") or "object").upper()
    allowed = {item.name for item in types.Type}
    schema_type = type_name if type_name in allowed else "OBJECT"
    kwargs: dict[str, Any] = {"type": schema_type}
    if (description := node.get("description")) is not None:
        kwargs["description"] = description
    properties = node.get("properties")
    if isinstance(properties, Mapping):
        kwargs["properties"] = {
            str(name): _schema(value)
            for name, value in properties.items()
            if isinstance(value, Mapping)
        }
    if isinstance(required := node.get("required"), list):
        kwargs["required"] = [str(item) for item in required]
    if isinstance(items := node.get("items"), Mapping):
        kwargs["items"] = _schema(items)
    if isinstance(enum := node.get("enum"), list):
        kwargs["enum"] = [str(item) for item in enum]
    return types.Schema(**kwargs)


def _image_part(part: ImagePart) -> types.Part:
    if part.data is not None:
        return types.Part.from_bytes(data=part.data, mime_type=part.media_type)
    if part.url is not None:
        # 远程图片: 用 file_data 让服务端自己去取
        return types.Part(
            file_data=types.FileData(file_uri=part.url, mime_type=part.media_type)
        )
    raise LLMConfigError("ImagePart 需要 url 或 data 之一")


def _tool_parts(call: ToolCall) -> types.Part:
    if not call.signature:
        # 少了签名上游会拒绝, 与其发一个必然 400 的请求, 不如在这里说清楚
        raise LLMConfigError(
            "Gemini 要求回传工具调用时带上 thought_signature; "
            "assistant 消息里的 ToolCall.signature 不能为空"
        )
    try:
        arguments = json.loads(call.arguments or "{}")
    except json.JSONDecodeError as exc:
        raise LLMConfigError(f"工具参数不是合法 JSON: {call.arguments[:80]}") from exc
    return types.Part(
        function_call=types.FunctionCall(id=call.id, name=call.name, args=arguments),
        thought_signature=_unb64(call.signature),
    )


def _message_parts(message: Message) -> list[types.Part]:
    parts: list[types.Part] = []
    for part in message.parts:
        if isinstance(part, ImagePart):
            parts.append(_image_part(part))
        else:
            parts.append(types.Part.from_text(text=part.text))
    parts.extend(_tool_parts(call) for call in message.tool_calls)
    return parts


def _build_contents(request: CompletionRequest) -> list[types.Content]:
    contents: list[types.Content] = []
    # 工具结果只带 id, Gemini 要的是函数名, 从前面 assistant 的调用里找
    names: dict[str, str] = {}
    for message in request.messages:
        if message.role == "assistant":
            for call in message.tool_calls:
                names[call.id] = call.name
            if message.parts or message.tool_calls:
                contents.append(
                    types.Content(role="model", parts=_message_parts(message))
                )
            continue
        if message.role == "tool":
            name = names.get(message.tool_call_id or "", "tool")
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=name, response={"result": message.text()}
                        )
                    ],
                )
            )
            continue
        contents.append(types.Content(role="user", parts=_message_parts(message)))
    return contents


def _tool_config(choice: Any) -> types.ToolConfig | None:
    mode = tool_choice_value(choice, style="chat")
    if mode is None or mode == "auto":
        return None
    if mode == "none":
        return types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="NONE")
        )
    if mode == "required":
        return types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="ANY")
        )
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode="ANY", allowed_function_names=[str(mode)]
        )
    )


def _thinking(
    reasoning: Reasoning | None, quirks: Quirks
) -> types.ThinkingConfig | None:
    if reasoning is None or reasoning.effort is None:
        return None
    effort = reasoning.effort
    if effort == "none":
        return types.ThinkingConfig(thinking_budget=0)
    level = _EFFORT_LEVEL.get(quirks.effort_map.get(effort, effort))
    return types.ThinkingConfig(thinking_level=level) if level else None


def build(request: CompletionRequest, *, model: str, quirks: Quirks) -> Translation:
    check_capabilities(request, quirks)
    config_kwargs: dict[str, Any] = {}
    if request.system:
        config_kwargs["system_instruction"] = request.system
    if request.max_tokens is not None:
        config_kwargs["max_output_tokens"] = request.max_tokens
    if request.temperature is not None and quirks.supports_temperature:
        config_kwargs["temperature"] = request.temperature
    if request.top_p is not None and quirks.supports_top_p:
        config_kwargs["top_p"] = request.top_p
    if request.stop and quirks.supports_stop:
        config_kwargs["stop_sequences"] = list(request.stop)
    if request.tools:
        config_kwargs["tools"] = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description,
                        parameters=_schema(tool.parameters),
                    )
                    for tool in request.tools
                ]
            )
        ]
        if (config := _tool_config(request.tool_choice)) is not None:
            config_kwargs["tool_config"] = config
    if request.json_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = _schema(request.json_schema)
    if (thinking := _thinking(request.reasoning, quirks)) is not None:
        config_kwargs["thinking_config"] = thinking

    body = {
        "model": model,
        "contents": _build_contents(request),
        "config": types.GenerateContentConfig(**config_kwargs),
    }
    return Translation(body=body)


def _usage(meta: types.GenerateContentResponseUsageMetadata | None) -> Usage | None:
    if meta is None:
        return None
    return Usage(
        input_tokens=meta.prompt_token_count or 0,
        output_tokens=meta.candidates_token_count or 0,
        cached_input_tokens=meta.cached_content_token_count or 0,
        reasoning_tokens=meta.thoughts_token_count or 0,
        total_tokens=meta.total_token_count or 0,
    )


def parse(obj: Any, acc: StreamAccumulator) -> list[StreamEvent]:
    events: list[StreamEvent] = []
    for candidate in obj.candidates or []:
        content = candidate.content
        parts = (content.parts if content else None) or []
        for index, part in enumerate(parts):
            if getattr(part, "thought", False):
                if part.text:
                    events.append(ReasoningDelta(part.text))
                if signature := _b64(part.thought_signature):
                    events.append(SignatureDelta(signature))
                continue
            call = getattr(part, "function_call", None)
            if call is not None:
                key = call.id or f"call-{index}"
                events.extend(
                    acc.start(
                        key,
                        call.id or key,
                        call.name or "",
                        _b64(part.thought_signature),
                    )
                )
                payload = json.dumps(
                    dict(call.args or {}), ensure_ascii=False, separators=(",", ":")
                )
                events.extend(acc.args(key, payload))
                continue
            if part.text:
                events.append(TextDelta(part.text))
        if (reason := candidate.finish_reason) is not None:
            name = getattr(reason, "name", str(reason))
            mapped = "tool_calls" if acc.calls else _FINISH.get(name, "stop")
            acc.finish(mapped)
    if (usage := _usage(obj.usage_metadata)) is not None:
        acc.absorb(usage)
    return events
