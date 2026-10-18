"""测试用的本地假端点

用真实 SSE 形状模拟 chat completions / responses / anthropic messages, 三个端点的语义内容相同
(两段思维链、两段正文、两个工具调用、一份含缓存读写的用量)。按请求里的 model 切换形状。
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

_CAPTURED = web.AppKey("captured", list)

NORMAL = "fake-model"
DS_SHAPE = "ds-shape"  # chat: usage 附在最后一个内容块上, 不单独下发
INCOMPLETE_SHAPE = "incomplete-shape"  # responses: response.incomplete
FAILED_SHAPE = "failed-shape"  # responses: response.failed
TRUNCATE_SHAPE = "truncate-shape"  # 任意协议: 发一半就断流
UNAUTHORIZED_SHAPE = "unauthorized-shape"  # 任意协议: 401
RATELIMIT_SHAPE = "ratelimit-shape"  # 任意协议: 429 + Retry-After

REASONING = ["先想想", "，再算算"]
TEXT = ["你好", "，主人"]
TOOLS = [
    ("get_time", ['{"tz":', '"Asia/Shanghai"}']),
    ("get_weather", ['{"city":', '"杭州"}']),
]
USAGE = {
    "input": 11,
    "uncached": 6,
    "cached": 3,
    "cache_write": 2,
    "output": 22,
    "reasoning": 7,
    "total": 33,
}
_CAPTURED_HEADERS = ("idempotency-key", "user-agent", "x-opencode-session")


@dataclass
class Captured:
    path: str
    body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


def _sse(data: dict[str, Any] | str, *, event: str | None = None) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {payload}\n\n"


def chat_chunks(model: str) -> list[str]:
    def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
        return _sse(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
        )

    usage = {
        "prompt_tokens": USAGE["input"],
        "completion_tokens": USAGE["output"],
        "total_tokens": USAGE["total"],
        "prompt_tokens_details": {
            "cached_tokens": USAGE["cached"],
            "cache_write_tokens": USAGE["cache_write"],
        },
        "completion_tokens_details": {"reasoning_tokens": USAGE["reasoning"]},
    }
    chunks = [
        chunk({"role": "assistant"}),
        chunk({"reasoning_content": REASONING[0]}),
        chunk({"reasoning_content": REASONING[1]}),
        chunk({"content": TEXT[0]}),
        chunk({"content": ""}),
        chunk({"content": TEXT[1]}),
    ]
    for index, (name, args) in enumerate(TOOLS):
        chunks.append(
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": f"call_{index + 1}",
                            "type": "function",
                            "function": {"name": name, "arguments": ""},
                        }
                    ]
                }
            )
        )
        chunks.extend(
            chunk({"tool_calls": [{"index": index, "function": {"arguments": piece}}]})
            for piece in args
        )
    if model == TRUNCATE_SHAPE:
        return chunks
    if model == DS_SHAPE:
        chunks.append(
            _sse(
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": None},
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": usage,
                }
            )
        )
        chunks.append("data: [DONE]\n\n")
        return chunks
    chunks.append(chunk({}, finish="tool_calls"))
    chunks.append(
        _sse(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [],
                "usage": usage,
            }
        )
    )
    chunks.append("data: [DONE]\n\n")
    return chunks


def _response_object(
    model: str, output: list[dict[str, Any]], status: str, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "temperature": 1.0,
        "top_p": 1.0,
        "store": False,
        "previous_response_id": None,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "metadata": {},
        "usage": {
            "input_tokens": USAGE["input"],
            "output_tokens": USAGE["output"],
            "total_tokens": USAGE["total"],
            "input_tokens_details": {
                "cached_tokens": USAGE["cached"],
                "cache_write_tokens": USAGE["cache_write"],
            },
            "output_tokens_details": {"reasoning_tokens": USAGE["reasoning"]},
        },
    }
    body.update(extra)
    return body


def responses_chunks(model: str) -> list[str]:
    reasoning_item = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [],
        "content": [{"type": "reasoning_text", "text": "".join(REASONING)}],
        "encrypted_content": None,
        "status": "completed",
    }
    message_item = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "".join(TEXT), "annotations": []}],
    }
    call_items = [
        {
            "type": "function_call",
            "id": f"fc_{index + 1}",
            "call_id": f"call_{index + 1}",
            "name": name,
            "arguments": "".join(args),
            "status": "completed",
        }
        for index, (name, args) in enumerate(TOOLS)
    ]
    chunks = [
        _sse(
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": _response_object(model, [], "in_progress"),
            },
            event="response.created",
        ),
        _sse(
            {
                "type": "response.output_item.added",
                "sequence_number": 1,
                "output_index": 0,
                "item": {**reasoning_item, "content": [], "status": "in_progress"},
            },
            event="response.output_item.added",
        ),
        *[
            _sse(
                {
                    "type": "response.reasoning_text.delta",
                    "sequence_number": 2 + i,
                    "item_id": "rs_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": piece,
                },
                event="response.reasoning_text.delta",
            )
            for i, piece in enumerate(REASONING)
        ],
        _sse(
            {
                "type": "response.output_item.done",
                "sequence_number": 10,
                "output_index": 0,
                "item": reasoning_item,
            },
            event="response.output_item.done",
        ),
        _sse(
            {
                "type": "response.output_item.added",
                "sequence_number": 11,
                "output_index": 1,
                "item": {**message_item, "content": [], "status": "in_progress"},
            },
            event="response.output_item.added",
        ),
        *[
            _sse(
                {
                    "type": "response.output_text.delta",
                    "sequence_number": 12 + i,
                    "item_id": "msg_1",
                    "output_index": 1,
                    "content_index": 0,
                    "logprobs": [],
                    "delta": piece,
                },
                event="response.output_text.delta",
            )
            for i, piece in enumerate(TEXT)
        ],
        _sse(
            {
                "type": "response.output_item.done",
                "sequence_number": 20,
                "output_index": 1,
                "item": message_item,
            },
            event="response.output_item.done",
        ),
    ]
    for offset, item in enumerate(call_items):
        output_index = offset + 2
        chunks.append(
            _sse(
                {
                    "type": "response.output_item.added",
                    "sequence_number": 21 + output_index,
                    "output_index": output_index,
                    "item": {**item, "arguments": "", "status": "in_progress"},
                },
                event="response.output_item.added",
            )
        )
        if offset == 0:
            chunks.extend(
                _sse(
                    {
                        "type": "response.function_call_arguments.delta",
                        "sequence_number": 30 + output_index,
                        "item_id": item["id"],
                        "output_index": output_index,
                        "delta": piece,
                    },
                    event="response.function_call_arguments.delta",
                )
                for piece in TOOLS[offset][1]
            )
        else:
            # 第二个工具只给 done 不给 delta, 覆盖"兼容层只发完整参数"的情形
            chunks.append(
                _sse(
                    {
                        "type": "response.function_call_arguments.done",
                        "sequence_number": 40,
                        "item_id": item["id"],
                        "output_index": output_index,
                        "arguments": item["arguments"],
                    },
                    event="response.function_call_arguments.done",
                )
            )
        chunks.append(
            _sse(
                {
                    "type": "response.output_item.done",
                    "sequence_number": 41 + output_index,
                    "output_index": output_index,
                    "item": item,
                },
                event="response.output_item.done",
            )
        )

    if model == TRUNCATE_SHAPE:
        return chunks
    if model == FAILED_SHAPE:
        chunks.append(
            _sse(
                {
                    "type": "response.failed",
                    "sequence_number": 90,
                    "response": _response_object(
                        model,
                        [],
                        "failed",
                        error={"code": "server_error", "message": "上游炸了"},
                    ),
                },
                event="response.failed",
            )
        )
        return chunks
    if model == INCOMPLETE_SHAPE:
        chunks.append(
            _sse(
                {
                    "type": "response.incomplete",
                    "sequence_number": 90,
                    "response": _response_object(
                        model,
                        [message_item],
                        "incomplete",
                        incomplete_details={"reason": "max_output_tokens"},
                    ),
                },
                event="response.incomplete",
            )
        )
        return chunks
    chunks.append(
        _sse(
            {
                "type": "response.completed",
                "sequence_number": 90,
                "response": _response_object(
                    model, [reasoning_item, message_item, *call_items], "completed"
                ),
            },
            event="response.completed",
        )
    )
    return chunks


def anthropic_chunks(model: str) -> list[str]:
    chunks = [
        _sse(
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        # input_tokens 不含缓存部分: 6 + 3 + 2 = 11
                        "input_tokens": USAGE["uncached"],
                        "output_tokens": 1,
                        "cache_read_input_tokens": USAGE["cached"],
                        "cache_creation_input_tokens": USAGE["cache_write"],
                    },
                },
            },
            event="message_start",
        ),
        _sse(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            },
            event="content_block_start",
        ),
        *[
            _sse(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": piece},
                },
                event="content_block_delta",
            )
            for piece in REASONING
        ],
        _sse(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig-1"},
            },
            event="content_block_delta",
        ),
        _sse({"type": "content_block_stop", "index": 0}, event="content_block_stop"),
        _sse(
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            event="content_block_start",
        ),
        _sse(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": ""},
            },
            event="content_block_delta",
        ),
        *[
            _sse(
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": piece},
                },
                event="content_block_delta",
            )
            for piece in TEXT
        ],
        _sse({"type": "content_block_stop", "index": 1}, event="content_block_stop"),
    ]
    for offset, (name, args) in enumerate(TOOLS):
        index = offset + 2
        chunks.append(
            _sse(
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {
                        "type": "tool_use",
                        "id": f"toolu_{offset + 1}",
                        "name": name,
                        "input": {},
                    },
                },
                event="content_block_start",
            )
        )
        chunks.extend(
            _sse(
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": piece},
                },
                event="content_block_delta",
            )
            for piece in args
        )
        chunks.append(
            _sse(
                {"type": "content_block_stop", "index": index},
                event="content_block_stop",
            )
        )
    if model == TRUNCATE_SHAPE:
        return chunks
    chunks.append(
        _sse(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {
                    "output_tokens": USAGE["output"],
                    "output_tokens_details": {"thinking_tokens": USAGE["reasoning"]},
                },
            },
            event="message_delta",
        )
    )
    chunks.append(_sse({"type": "message_stop"}, event="message_stop"))
    return chunks


# --------------------------------------------------------------------------
# 校验与路由
# --------------------------------------------------------------------------


def _error(protocol: str, message: str, status: int) -> web.Response:
    return web.json_response(
        {
            "error": {
                "message": f"{protocol}: {message}",
                "type": "invalid_request_error",
            }
        },
        status=status,
    )


def validate_chat(body: dict[str, Any]) -> str | None:
    if not body.get("model"):
        return "缺少 model"
    if not body.get("messages"):
        return "缺少 messages"
    for message in body["messages"]:
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            return f"未知 role: {role}"
        if (
            role == "assistant"
            and not message.get("content")
            and not message.get("tool_calls")
        ):
            return "空 assistant 消息"
    return None


def validate_responses(body: dict[str, Any]) -> str | None:
    if not body.get("model"):
        return "缺少 model"
    if not body.get("input") and not body.get("instructions"):
        return "input 与 instructions 至少要有一个"
    return None


def validate_messages(body: dict[str, Any]) -> str | None:
    if not body.get("model"):
        return "缺少 model"
    if not body.get("messages"):
        return "缺少 messages"
    max_tokens = body.get("max_tokens")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        return "max_tokens 必须是正整数"
    thinking = body.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        budget = thinking.get("budget_tokens", 0)
        if not isinstance(budget, int) or budget < 1024:
            return "thinking.budget_tokens 至少 1024"
        if budget >= max_tokens:
            return "thinking.budget_tokens 必须小于 max_tokens"
    return None


@dataclass(frozen=True)
class Route:
    protocol: str
    chunks: Any
    validate: Any


async def _stream(request: web.Request, route: Route) -> web.StreamResponse:
    body = await request.json()
    headers = {
        k.lower(): v
        for k, v in request.headers.items()
        if k.lower() in _CAPTURED_HEADERS
    }
    request.app[_CAPTURED].append(Captured(request.path, body, headers))

    if body["model"] == UNAUTHORIZED_SHAPE:
        return _error(route.protocol, "invalid api key", 401)
    if body["model"] == RATELIMIT_SHAPE:
        return web.json_response(
            {
                "error": {
                    "message": f"{route.protocol}: slow down",
                    "type": "rate_limit",
                }
            },
            status=429,
            headers={"Retry-After": "2"},
        )

    problem = route.validate(body)
    if problem is not None:
        return _error(route.protocol, problem, 400)

    response = web.StreamResponse(
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
    )
    await response.prepare(request)
    for chunk in route.chunks(body["model"]):
        await response.write(chunk.encode())
        await asyncio.sleep(0)
    await response.write_eof()
    return response


def build_app() -> web.Application:
    app = web.Application()
    app[_CAPTURED] = []
    routes = {
        "/v1/chat/completions": Route("chat", chat_chunks, validate_chat),
        "/v1/responses": Route("responses", responses_chunks, validate_responses),
        "/v1/messages": Route("anthropic", anthropic_chunks, validate_messages),
    }
    for path, route in routes.items():

        async def handler(
            request: web.Request, route: Route = route
        ) -> web.StreamResponse:
            return await _stream(request, route)

        app.router.add_post(path, handler)
    return app


@asynccontextmanager
async def fake_endpoint() -> AsyncGenerator[tuple[str, list[Captured]]]:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    # 自己 bind 临时端口, 比事后从私有属性里挖更稳
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    site = web.SockSite(runner, sock)
    await site.start()
    try:
        yield f"http://127.0.0.1:{port}", app[_CAPTURED]
    finally:
        await runner.cleanup()
