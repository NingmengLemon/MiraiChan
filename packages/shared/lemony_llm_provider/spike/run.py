"""原型入口: 让三套真 SDK 打本地假端点, 校验请求翻译、流式归一化与错误处理

用法: uv run python packages/shared/lemony_llm_provider/spike/run.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import anthropic
import openai
from fake_server import (
    DS_SHAPE,
    FAILED_SHAPE,
    INCOMPLETE_SHAPE,
    NORMAL,
    TRUNCATE_SHAPE,
    fake_endpoint,
)
from unified import (
    Accumulator,
    Completed,
    CompletionRequest,
    ImagePart,
    Message,
    Reasoning,
    ReasoningDelta,
    SignatureDelta,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolSpec,
    Translation,
    Usage,
    from_anthropic_event,
    from_chat_chunk,
    from_responses_event,
    to_anthropic,
    to_chat,
    to_responses,
)

FAILURES: list[str] = []


def check(condition: bool, what: str) -> None:
    if condition:
        print(f"  ok   {what}")
    else:
        print(f"  FAIL {what}")
        FAILURES.append(what)


def eq(actual: Any, expected: Any, what: str) -> None:
    check(actual == expected, f"{what} (期望 {expected!r}, 实际 {actual!r})")


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
    ToolSpec(
        name="get_weather",
        description="查天气",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    ),
)

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def full_request() -> CompletionRequest:
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


def with_reasoning(reasoning: Reasoning) -> CompletionRequest:
    base = full_request()
    return CompletionRequest(
        messages=base.messages,
        system=base.system,
        tools=base.tools,
        tool_choice=base.tool_choice,
        reasoning=reasoning,
        max_tokens=base.max_tokens,
        temperature=base.temperature,
        stop=base.stop,
    )


def structured_request() -> CompletionRequest:
    base = full_request()
    return CompletionRequest(
        messages=base.messages,
        system=base.system,
        json_schema=SCHEMA,
        json_schema_name="answer_v1",
        reasoning=base.reasoning,
        max_tokens=base.max_tokens,
    )


# --------------------------------------------------------------------------
# 请求侧
# --------------------------------------------------------------------------


def check_translation() -> None:
    print("\n[请求翻译]")
    req = full_request()
    chat: Translation = to_chat(req, model="m")
    resp: Translation = to_responses(req, model="m")
    anth: Translation = to_anthropic(req, model="m")

    eq(chat.body["messages"][0]["role"], "system", "chat: system 落在第一条消息")
    eq(len(chat.body["messages"]), 2, "chat: 空 assistant 消息被丢弃")
    eq(
        chat.body["messages"][1]["content"][1],
        {"type": "image_url", "image_url": {"url": "https://example.invalid/x.png"}},
        "chat: 图片走 image_url",
    )
    eq(
        chat.body["tools"][0]["function"]["name"],
        "get_time",
        "chat: 工具嵌套在 function 下",
    )
    eq(chat.body["reasoning_effort"], "low", "chat: reasoning_effort")
    eq(chat.body["max_tokens"], 2048, "chat: max_tokens")
    eq(chat.body["stop"], ["STOP"], "chat: stop")
    eq(chat.body["stream_options"], {"include_usage": True}, "chat: 要求下发用量")
    eq(chat.dropped, (), "chat: 没有丢弃参数")

    eq(resp.body["instructions"], "你是一只猫娘", "responses: system 走 instructions")
    eq(resp.body["tools"][0]["name"], "get_time", "responses: 工具是扁平结构")
    eq(resp.body["reasoning"], {"effort": "low"}, "responses: reasoning.effort")
    eq(resp.body["max_output_tokens"], 2048, "responses: max_output_tokens")
    check("stop" not in resp.body, "responses: 没有 stop 参数")
    eq(resp.dropped, ("stop",), "responses: stop 被记为丢弃")

    eq(anth.body["system"], "你是一只猫娘", "anthropic: system 走顶层参数")
    eq(anth.body["max_tokens"], 2048, "anthropic: max_tokens")
    eq(
        anth.body["thinking"],
        {"type": "enabled", "budget_tokens": 1024},
        "anthropic: thinking.enabled",
    )
    eq(anth.body["stop_sequences"], ["STOP"], "anthropic: stop_sequences")
    check("temperature" not in anth.body, "anthropic: 没有 temperature")
    eq(anth.dropped, ("temperature",), "anthropic: temperature 被记为丢弃")

    structured = structured_request()
    eq(
        to_chat(structured, model="m").body["response_format"]["json_schema"]["name"],
        "answer_v1",
        "chat: response_format 带 name",
    )
    eq(
        to_responses(structured, model="m").body["text"]["format"]["schema"],
        SCHEMA,
        "responses: text.format.schema",
    )
    eq(
        to_anthropic(structured, model="m").body["output_config"]["format"]["schema"],
        SCHEMA,
        "anthropic: output_config.format.schema",
    )

    print("\n[effort 折叠]")
    for effort, folded in (("minimal", "low"), ("xhigh", "high"), ("ultra", "max")):
        req_e = with_reasoning(Reasoning(effort=effort))
        eq(
            to_chat(req_e, model="m").body["reasoning_effort"],
            folded,
            f"chat: {effort} -> {folded}",
        )
        eq(
            to_anthropic(req_e, model="m").body["output_config"]["effort"],
            folded,
            f"anthropic: {effort} -> {folded}",
        )
    req_none = with_reasoning(Reasoning(effort="none"))
    eq(
        to_chat(req_none, model="m").body.get("thinking"),
        {"type": "disabled"},
        "chat: effort=none 关掉 thinking",
    )
    check(
        "reasoning_effort" not in to_chat(req_none, model="m").body,
        "chat: effort=none 不发 reasoning_effort",
    )
    eq(
        to_responses(req_none, model="m").body["reasoning"],
        {"effort": "none"},
        "responses: effort=none 直接透传",
    )
    eq(
        to_anthropic(req_none, model="m").body.get("thinking"),
        {"type": "disabled"},
        "anthropic: effort=none 关掉 thinking",
    )

    print("\n[anthropic 预算约束]")
    too_small = with_reasoning(Reasoning(budget_tokens=1024))
    too_small = CompletionRequest(
        messages=too_small.messages,
        system=too_small.system,
        reasoning=too_small.reasoning,
        max_tokens=256,
    )
    try:
        to_anthropic(too_small, model="m")
    except ValueError as exc:
        check("budget_tokens" in str(exc), "预算不小于 max_tokens 时提前报错")
    else:
        check(False, "预算不小于 max_tokens 时提前报错")


def check_roundtrip() -> None:
    print("\n[回传 assistant 的 reasoning 与工具调用]")
    first = Message.assistant(
        "我去查一下",
        ToolCall("call_1", "get_time", '{"tz":"Asia/Shanghai"}'),
        ToolCall("call_2", "get_weather", '{"city":"杭州"}'),
        reasoning="先想想，再算算",
        signature="sig-1",
    )
    req = CompletionRequest(
        system="你是一只猫娘",
        messages=(
            Message.user("现在几点?"),
            first,
            Message.tool_result("call_1", "12:00"),
            Message.tool_result("call_2", "晴"),
        ),
        tools=TOOLS,
        max_tokens=2048,
    )
    chat = to_chat(req, model="m").body
    assistant = chat["messages"][2]  # [system, user, assistant, tool, tool]
    eq(assistant["reasoning_content"], "先想想，再算算", "chat: 回传 reasoning_content")
    eq(len(assistant["tool_calls"]), 2, "chat: 回传两个工具调用")
    eq(chat["messages"][3]["role"], "tool", "chat: 工具结果走 role=tool")
    eq(chat["messages"][3]["tool_call_id"], "call_1", "chat: 工具结果带 tool_call_id")

    anth = to_anthropic(req, model="m").body
    blocks = anth["messages"][1]["content"]
    eq(
        blocks[0],
        {"type": "thinking", "thinking": "先想想，再算算", "signature": "sig-1"},
        "anthropic: thinking 块带 signature 且排在最前",
    )
    eq(
        [b["type"] for b in blocks[1:]],
        ["text", "tool_use", "tool_use"],
        "anthropic: 正文与工具块顺序",
    )
    results = anth["messages"][2]
    eq(results["role"], "user", "anthropic: 工具结果放进 user 消息")
    eq(
        [b["tool_use_id"] for b in results["content"]],
        ["call_1", "call_2"],
        "anthropic: 同轮的多条工具结果合并进同一条 user 消息",
    )

    resp = to_responses(req, model="m").body
    kinds = [item.get("type") or item.get("role") for item in resp["input"]]
    eq(
        kinds,
        [
            "user",
            "assistant",
            "function_call",
            "function_call",
            "function_call_output",
            "function_call_output",
        ],
        "responses: 工具调用与结果拆成独立 item",
    )


# --------------------------------------------------------------------------
# 响应侧
# --------------------------------------------------------------------------


@dataclass
class Run:
    events: list[StreamEvent]
    completed: Completed


async def drain(stream: Any, parse: Any) -> Run:
    acc = Accumulator()
    events: list[StreamEvent] = []
    try:
        async for item in stream:
            events.extend(parse(item, acc))
    finally:
        await stream.close()
    return Run(events, acc.completed())


async def run_chat(base: str, model: str) -> Run:
    client = openai.AsyncOpenAI(api_key="sk-fake", base_url=f"{base}/v1", max_retries=0)
    body = to_chat(full_request(), model=model).body
    stream = await client.chat.completions.create(**body)
    return await drain(stream, from_chat_chunk)


async def run_responses(base: str, model: str) -> Run:
    client = openai.AsyncOpenAI(api_key="sk-fake", base_url=f"{base}/v1", max_retries=0)
    body = to_responses(full_request(), model=model).body
    stream = await client.responses.create(**body)
    return await drain(stream, from_responses_event)


async def run_anthropic(base: str, model: str) -> Run:
    client = anthropic.AsyncAnthropic(api_key="sk-fake", base_url=base, max_retries=0)
    body = to_anthropic(full_request(), model=model).body
    stream = await client.messages.create(**body)
    return await drain(stream, from_anthropic_event)


def semantic(run: Run) -> dict[str, Any]:
    """只取跨协议应当一致的语义, 不含各协议自己生成的 id"""
    text = "".join(e.text for e in run.events if isinstance(e, TextDelta))
    reasoning = "".join(e.text for e in run.events if isinstance(e, ReasoningDelta))
    return {
        "text": text,
        "reasoning": reasoning,
        "calls": [(c.name, c.arguments) for c in run.completed.tool_calls],
        "finish": run.completed.finish_reason,
        "usage": run.completed.usage,
    }


EXPECTED = {
    "text": "你好，主人",
    "reasoning": "先想想，再算算",
    "calls": [
        ("get_time", '{"tz":"Asia/Shanghai"}'),
        ("get_weather", '{"city":"杭州"}'),
    ],
    "finish": "tool_calls",
    "usage": Usage(
        input_tokens=11,
        output_tokens=22,
        cached_input_tokens=3,
        cache_write_input_tokens=2,
        reasoning_tokens=7,
        total_tokens=33,
    ),
}


def check_ids(run: Run) -> None:
    ids = [c.id for c in run.completed.tool_calls]
    check(all(ids), f"工具调用都有 id: {ids}")
    check(len(set(ids)) == len(ids), f"工具调用 id 不重复: {ids}")
    check(len(run.completed.tool_calls) == 2, "两个工具调用都被拼出来")


async def check_streams(base: str) -> None:
    print("\n[流式归一化: 正常形状]")
    runs = {
        "chat": await run_chat(base, NORMAL),
        "responses": await run_responses(base, NORMAL),
        "anthropic": await run_anthropic(base, NORMAL),
    }
    for name, run in runs.items():
        eq(semantic(run), EXPECTED, f"{name}: 归一化语义")
        check_ids(run)

    sigs = [e for e in runs["anthropic"].events if isinstance(e, SignatureDelta)]
    eq(len(sigs), 1, "anthropic: signature 作为独立事件下发")

    print("\n[DeepSeek 末块 usage]")
    ds = await run_chat(base, DS_SHAPE)
    eq(semantic(ds), EXPECTED, "chat(DeepSeek 形状): 归一化语义")

    print("\n[截断与报错]")
    for name, runner in (
        ("chat", run_chat),
        ("responses", run_responses),
        ("anthropic", run_anthropic),
    ):
        try:
            await runner(base, TRUNCATE_SHAPE)
        except Exception as exc:  # noqa: BLE001
            check(
                type(exc).__name__ == "SpikeTruncated",
                f"{name}: 断流被判为截断 ({type(exc).__name__})",
            )
        else:
            check(False, f"{name}: 断流被判为截断")

    try:
        await run_responses(base, FAILED_SHAPE)
    except Exception as exc:  # noqa: BLE001
        check(
            type(exc).__name__ == "SpikeApiError" and "server_error" in str(exc),
            f"responses: response.failed 抛错 ({type(exc).__name__}: {exc})",
        )
    else:
        check(False, "responses: response.failed 抛错")

    print("\n[未完成]")
    incomplete = await run_responses(base, INCOMPLETE_SHAPE)
    eq(
        incomplete.completed.finish_reason,
        "length",
        "responses: max_output_tokens 映射成 length",
    )


async def main() -> int:
    check_translation()
    check_roundtrip()
    async with fake_endpoint() as (base, _captured):
        await check_streams(base)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
