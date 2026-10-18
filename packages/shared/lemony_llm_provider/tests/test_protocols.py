"""协议翻译层的单元测试: 只看请求体形状与回传规则, 不发请求"""

from __future__ import annotations

from typing import Literal

import pytest
from lemony_llm_provider import (
    CompletionRequest,
    ImagePart,
    LLMConfigError,
    Message,
    Reasoning,
    ToolCall,
    ToolSpec,
    protocols,
    resolve_quirks,
)

TOOLS = (
    ToolSpec(
        name="get_time",
        description="查当前时间",
        parameters={
            "type": "object",
            "properties": {"tz": {"type": "string"}},
            "required": ["tz"],
        },
    ),
)

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def base_request() -> CompletionRequest:
    return CompletionRequest(
        system="你是一只猫娘",
        messages=(
            Message.user("现在几点?", ImagePart(url="https://example.invalid/x.png")),
            Message.assistant(""),  # 空 assistant 消息应当被丢弃
        ),
        tools=TOOLS,
        tool_choice="auto",
        reasoning=Reasoning(effort="low", budget_tokens=1024),
        max_tokens=2048,
        temperature=0.7,
        stop=("STOP",),
    )


def build(protocol: str, request: CompletionRequest, quirks: str = "generic"):
    module = protocols.for_protocol(protocol)
    return module.build(request, model="m", quirks=resolve_quirks(quirks))


def test_chat_translation() -> None:
    result = build("chat", base_request())
    body = result.body
    assert body["messages"][0] == {"role": "system", "content": "你是一只猫娘"}
    assert len(body["messages"]) == 2  # 空 assistant 被丢掉
    assert body["messages"][1]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "https://example.invalid/x.png"},
    }
    assert body["tools"][0]["function"]["name"] == "get_time"
    assert body["tool_choice"] == "auto"
    assert body["reasoning_effort"] == "low"
    assert body["max_tokens"] == 2048
    assert body["stop"] == ["STOP"]
    assert body["stream_options"] == {"include_usage": True}
    assert result.dropped == ()


def test_responses_translation() -> None:
    result = build("responses", base_request())
    body = result.body
    assert body["instructions"] == "你是一只猫娘"
    assert body["tools"][0]["name"] == "get_time"
    assert body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] == 2048
    assert "stop" not in body
    assert result.dropped == ("stop",)


def test_anthropic_translation() -> None:
    result = build("anthropic", base_request())
    body = result.body
    assert body["system"] == "你是一只猫娘"
    assert body["max_tokens"] == 2048
    # 新一代 Claude 用 adaptive, 预算在这条路上没有落点
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "low"}
    assert "thinking.budget_tokens" in result.dropped
    assert body["stop_sequences"] == ["STOP"]
    assert "temperature" not in body
    # messages.create 没有 temperature 参数, 端点声明支持时只能走 extra_body
    assert result.extra["temperature"] == 0.7


def test_structured_output_shapes() -> None:
    request = CompletionRequest(
        messages=(Message.user("给个 JSON"),),
        json_schema=SCHEMA,
        json_schema_name="answer_v1",
        max_tokens=1024,
    )
    chat = build("chat", request).body
    responses = build("responses", request).body
    anthropic = build("anthropic", request).body
    assert chat["response_format"]["json_schema"]["name"] == "answer_v1"
    assert responses["text"]["format"]["schema"] == SCHEMA
    # anthropic 的 JSON Schema 没有 name 字段
    assert anthropic["output_config"]["format"] == {
        "type": "json_schema",
        "schema": SCHEMA,
    }


@pytest.mark.parametrize(
    ("effort", "folded"), [("minimal", "low"), ("xhigh", "high"), ("ultra", "max")]
)
def test_deepseek_effort_folding(
    effort: Literal["minimal", "xhigh", "ultra"], folded: str
) -> None:
    request = CompletionRequest(
        messages=(Message.user("hi"),), reasoning=Reasoning(effort=effort)
    )  # type: ignore[arg-type]
    assert build("chat", request, "deepseek_chat").body["reasoning_effort"] == folded
    assert (
        build("anthropic", request, "deepseek_anthropic").body["output_config"][
            "effort"
        ]
        == folded
    )


def test_effort_none_disables_thinking() -> None:
    request = CompletionRequest(
        messages=(Message.user("hi"),), reasoning=Reasoning(effort="none")
    )
    deepseek = build("chat", request, "deepseek_chat")
    # thinking 不是 SDK 的原生参数, 必须走 extra_body, 否则调用处会 TypeError
    assert deepseek.extra["thinking"] == {"type": "disabled"}
    assert "thinking" not in deepseek.body
    assert "reasoning_effort" not in deepseek.body
    # OpenAI 侧没有 thinking 开关, 什么都不发
    openai_chat = build("chat", request, "openai_chat")
    assert "thinking" not in openai_chat.body
    assert build("anthropic", request).body["thinking"] == {"type": "disabled"}


def test_responses_always_opts_out_of_storage() -> None:
    # responses 的 store 默认是 true, 不显式关掉就等于让服务端留存对话
    assert build("responses", base_request()).body["store"] is False


def test_extra_body_is_kept_out_of_native_kwargs() -> None:
    request = CompletionRequest(
        messages=(Message.user("hi"),), extra_body={"provider_specific": 1}
    )
    for protocol in ("chat", "responses", "anthropic"):
        result = build(protocol, request)
        assert result.extra["provider_specific"] == 1
        assert "provider_specific" not in result.body


def test_anthropic_temperature_goes_to_extra_when_enabled() -> None:
    from lemony_llm_provider import Quirks

    request = CompletionRequest(messages=(Message.user("hi"),), temperature=0.3)
    quirks = Quirks(supports_temperature=True, supports_top_p=True)
    module = protocols.for_protocol("anthropic")
    result = module.build(request, model="m", quirks=quirks)
    # SDK 类型层没有这个参数, 只能走 extra_body
    assert result.extra["temperature"] == 0.3
    assert "temperature" not in result.body
    assert result.dropped == ()


def test_anthropic_budgeted_style_validates_budget() -> None:
    request = CompletionRequest(
        messages=(Message.user("hi"),),
        reasoning=Reasoning(budget_tokens=1024),
        max_tokens=256,
    )
    with pytest.raises(LLMConfigError, match="budget_tokens"):
        build("anthropic", request, "anthropic_budgeted")
    # adaptive 风格没有预算概念, 不能因此报错, 只是丢掉
    adaptive = build("anthropic", request)
    assert adaptive.body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert "thinking.budget_tokens" in adaptive.dropped


def test_assistant_roundtrip_keeps_reasoning_and_tools() -> None:
    first = Message.assistant(
        "我去查一下",
        ToolCall("call_1", "get_time", '{"tz":"Asia/Shanghai"}'),
        ToolCall("call_2", "get_weather", '{"city":"杭州"}'),
        reasoning="先想想，再算算",
        signature="sig-1",
    )
    request = CompletionRequest(
        system="你是一只猫娘",
        messages=(
            Message.user("现在几点?"),
            first,
            Message.tool_result("call_1", "12:00"),
            Message.tool_result("call_2", "晴", is_error=True),
        ),
        tools=TOOLS,
        max_tokens=2048,
    )

    chat = build("chat", request).body
    assistant = chat["messages"][2]  # [system, user, assistant, tool, tool]
    assert assistant["reasoning_content"] == "先想想，再算算"
    assert [c["id"] for c in assistant["tool_calls"]] == ["call_1", "call_2"]
    assert chat["messages"][3]["tool_call_id"] == "call_1"

    anthropic = build("anthropic", request).body
    blocks = anthropic["messages"][1]["content"]
    assert blocks[0] == {
        "type": "thinking",
        "thinking": "先想想，再算算",
        "signature": "sig-1",
    }
    assert [b["type"] for b in blocks[1:]] == ["text", "tool_use", "tool_use"]
    results = anthropic["messages"][2]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["call_1", "call_2"]
    assert results["content"][1]["is_error"] is True

    responses = build("responses", request).body
    kinds = [item.get("type") or item.get("role") for item in responses["input"]]
    assert kinds == [
        "user",
        "assistant",
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]


def test_anthropic_keeps_signature_only_thinking_block() -> None:
    # 新版 Claude 可能只回签名不回正文, 这种块也必须原样带回去
    message = Message.assistant("答", signature="sig-only")
    request = CompletionRequest(messages=(Message.user("hi"), message), max_tokens=1024)
    blocks = build("anthropic", request).body["messages"][1]["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "", "signature": "sig-only"}
    assert blocks[1] == {"type": "text", "text": "答"}


def test_capability_mismatch_is_rejected_before_sending() -> None:
    from lemony_llm_provider import Quirks

    request = CompletionRequest(messages=(Message.user("hi"),), json_schema=SCHEMA)
    quirks = Quirks(supports_json_schema=False)
    module = protocols.for_protocol("chat")
    with pytest.raises(LLMConfigError, match="JSON Schema"):
        module.build(request, model="m", quirks=quirks)
