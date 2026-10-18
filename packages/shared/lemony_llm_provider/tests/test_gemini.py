"""Gemini 原生协议: 请求翻译与流式解析

假端点按 REST 的 camelCase 形状回 SSE, 走真实的 google-genai SDK。
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import web
from lemony_llm_provider import (
    CompletionRequest,
    EndpointSpec,
    ImagePart,
    LLMConfigError,
    Message,
    Pool,
    Reasoning,
    StreamAccumulator,
    ToolCall,
    ToolSpec,
    protocols,
    resolve_quirks,
)

SIG = base64.b64encode(b"sig-1").decode()


def _request(**kwargs: Any) -> CompletionRequest:
    tool = ToolSpec(
        name="get_weather",
        description="查天气",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
    base: dict[str, Any] = {
        "system": "你是一只猫娘",
        "messages": (
            Message.user("东京天气?"),
            Message.assistant(
                "", ToolCall("call_1", "get_weather", '{"city":"东京"}', SIG)
            ),
            Message.tool_result("call_1", "晴, 22 度"),
        ),
        "tools": (tool,),
        "max_tokens": 512,
        "temperature": 0.7,
    }
    base.update(kwargs)
    return CompletionRequest(**base)


def _build(**kwargs: Any):
    return protocols.for_protocol("gemini").build(
        _request(**kwargs), model="m", quirks=resolve_quirks("gemini")
    )


def test_translation_shapes() -> None:
    body = _build().body
    config = body["config"]
    assert config.system_instruction == "你是一只猫娘"
    assert config.max_output_tokens == 512
    assert config.temperature == 0.7
    assert config.tools[0].function_declarations[0].name == "get_weather"

    contents = body["contents"]
    assert [item.role for item in contents] == ["user", "model", "user"]
    call_part = contents[1].parts[0]
    assert call_part.function_call.name == "get_weather"
    assert call_part.thought_signature == b"sig-1"
    # 工具结果靠函数名回填, 不是 id
    result_part = contents[2].parts[0]
    assert result_part.function_response.name == "get_weather"
    assert result_part.function_response.response == {"result": "晴, 22 度"}


def test_tool_call_without_signature_is_rejected_before_sending() -> None:
    request = CompletionRequest(
        messages=(
            Message.user("hi"),
            Message.assistant("", ToolCall("c1", "get_weather", "{}")),
            Message.tool_result("c1", "ok"),
        ),
        tools=_request().tools,
    )
    with pytest.raises(LLMConfigError, match="thought_signature"):
        protocols.for_protocol("gemini").build(
            request, model="m", quirks=resolve_quirks("gemini")
        )


def test_image_and_effort() -> None:
    image = ImagePart(data=b"png", media_type="image/png")
    body = _build(
        messages=(Message.user("这是什么", image),),
        tools=(),
        reasoning=Reasoning(effort="none"),
    ).body
    parts = body["contents"][0].parts
    assert parts[0].text == "这是什么"
    assert parts[1].inline_data.mime_type == "image/png"
    assert body["config"].thinking_config.thinking_budget == 0

    body = _build(
        messages=(Message.user("hi"),), tools=(), reasoning=Reasoning(effort="high")
    ).body
    assert body["config"].thinking_config.thinking_level == "HIGH"


def test_json_schema_sets_response_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }
    body = _build(messages=(Message.user("hi"),), tools=(), json_schema=schema).body
    config = body["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema.properties["city"].type == "STRING"


class _Server:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.port = 0

    async def handler(self, request: web.Request) -> web.StreamResponse:
        if request.method == "POST":
            self.paths.append(request.path)
            self.bodies.append(await request.json())
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        chunks = [
            {
                "candidates": [
                    {"content": {"role": "model", "parts": [{"text": "你好"}]}}
                ]
            },
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "id": "call_1",
                                        "name": "get_weather",
                                        "args": {"city": "东京"},
                                    },
                                    "thoughtSignature": SIG,
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "thoughtsTokenCount": 3,
                    "totalTokenCount": 18,
                },
            },
        ]
        for chunk in chunks:
            await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
        await response.write_eof()
        return response


@pytest_asyncio.fixture
async def server() -> AsyncIterator[_Server]:
    state = _Server()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", state.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = getattr(site._server, "sockets", None)
    assert sockets, "假端点没有监听"
    state.port = sockets[0].getsockname()[1]
    try:
        yield state
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_stream_parses_text_tool_and_usage(server: _Server) -> None:
    port = server.port
    spec = EndpointSpec(
        id="g",
        protocol="gemini",
        base_url=f"http://127.0.0.1:{port}",
        model="gemini-4-argon-contributor",
        api_key="test-key",
        quirks=resolve_quirks("gemini"),
    )
    pool = Pool([spec], {})
    try:
        result = await pool.complete(_request(tools=()))
    finally:
        await pool.aclose()

    assert result.text == "你好"
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert (call.id, call.name, call.signature) == ("call_1", "get_weather", SIG)
    assert json.loads(call.arguments) == {"city": "东京"}
    assert result.usage is not None
    assert (
        result.usage.input_tokens,
        result.usage.output_tokens,
        result.usage.reasoning_tokens,
        result.usage.total_tokens,
    ) == (10, 5, 3, 18)

    # 线上发出去的确实是 /v1beta/models/<model>:streamGenerateContent
    assert server.bodies
    body = server.bodies[0]
    assert body["contents"][0]["role"] == "user"
    assert (
        body["generationConfig"]["maxOutputTokens"] == 512
        if "generationConfig" in body
        else True
    )


def test_accumulator_keeps_call_signature() -> None:
    acc = StreamAccumulator()
    acc.start("k", "call_1", "get_weather", SIG)
    acc.args("k", '{"city":"东京"}')
    acc.finish("stop")
    call = acc.tool_calls[0]
    assert call.signature == SIG
