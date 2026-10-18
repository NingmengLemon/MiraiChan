"""端点池的端到端测试: 真 SDK 打本地假端点, 覆盖轮询、冷却、失败换端点与归一化"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

import pytest
import pytest_asyncio
from fake_endpoint import (
    DS_SHAPE,
    FAILED_SHAPE,
    INCOMPLETE_SHAPE,
    NORMAL,
    RATELIMIT_SHAPE,
    TRUNCATE_SHAPE,
    UNAUTHORIZED_SHAPE,
    Captured,
    fake_endpoint,
)
from lemony_llm_provider import (
    DEFAULT_USER_AGENT,
    Completion,
    CompletionRequest,
    EndpointSpec,
    LLMConfigError,
    Message,
    Pool,
    Quirks,
    StreamAborted,
    ToolSpec,
    Usage,
    resolve_quirks,
)

pytestmark = pytest.mark.asyncio

ProtocolName = Literal["chat", "responses", "anthropic"]

EXPECTED_TEXT = "你好，主人"
EXPECTED_REASONING = "先想想，再算算"
EXPECTED_CALLS = [
    ("get_time", '{"tz":"Asia/Shanghai"}'),
    ("get_weather", '{"city":"杭州"}'),
]
EXPECTED_USAGE = Usage(
    input_tokens=11,
    output_tokens=22,
    cached_input_tokens=3,
    cache_write_input_tokens=2,
    reasoning_tokens=7,
    total_tokens=33,
)
TOOLS = (
    ToolSpec(
        name="get_time",
        description="查当前时间",
        parameters={"type": "object", "properties": {"tz": {"type": "string"}}},
    ),
)


def make_request() -> CompletionRequest:
    return CompletionRequest(
        system="你是一只猫娘",
        messages=(Message.user("现在几点?"),),
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=2048,
    )


def make_spec(
    base: str,
    *,
    key: str,
    protocol: ProtocolName,
    model: str = NORMAL,
    quirks: str = "generic",
    session_header: str | None = None,
) -> EndpointSpec:
    # openai SDK 自己追加 /chat/completions 与 /responses; anthropic 追加 /v1/messages
    base_url = base if protocol == "anthropic" else f"{base}/v1"
    return EndpointSpec(
        id=key,
        protocol=protocol,
        base_url=base_url,
        model=model,
        api_key="sk-test",
        quirks=resolve_quirks(quirks),
        session_header=session_header,
    )


@dataclass
class _Env:
    base: str
    captured: list[Captured]


@pytest_asyncio.fixture
async def env() -> AsyncIterator[_Env]:
    async with fake_endpoint() as (base, captured):
        yield _Env(base, captured)


async def _complete(pool: Pool, alias: str) -> Completion:
    return await pool.complete(make_request(), alias=alias)


def _semantic(result: Completion) -> tuple[object, ...]:
    return (
        result.text,
        result.reasoning,
        [(c.name, c.arguments) for c in result.tool_calls],
        result.finish_reason,
        result.usage,
    )


async def test_three_protocols_agree(env: _Env) -> None:
    specs = [
        make_spec(env.base, key="c", protocol="chat"),
        make_spec(env.base, key="r", protocol="responses"),
        make_spec(env.base, key="a", protocol="anthropic"),
    ]
    pool = Pool(specs, {"chat": ["c"], "responses": ["r"], "anthropic": ["a"]})
    try:
        results = {
            alias: await _complete(pool, alias)
            for alias in ("chat", "responses", "anthropic")
        }
    finally:
        await pool.aclose()

    expected = (
        EXPECTED_TEXT,
        EXPECTED_REASONING,
        EXPECTED_CALLS,
        "tool_calls",
        EXPECTED_USAGE,
    )
    for alias, result in results.items():
        assert _semantic(result) == expected, alias

    # 工具调用 id 由各协议自己生成, 只要求非空不重复
    for result in results.values():
        ids = [call.id for call in result.tool_calls]
        assert all(ids)
        assert len(set(ids)) == len(ids)

    assert results["anthropic"].signature == "sig-1"
    assert [r.endpoint_id for r in results.values()] == ["c", "r", "a"]


async def test_deepseek_style_usage_on_last_chunk(env: _Env) -> None:
    pool = Pool([make_spec(env.base, key="ds", protocol="chat", model=DS_SHAPE)], {})
    try:
        result = await _complete(pool, "default")
    finally:
        await pool.aclose()
    assert result.usage == EXPECTED_USAGE
    assert result.text == EXPECTED_TEXT


async def test_completed_response_failure_aborts(env: _Env) -> None:
    pool = Pool(
        [make_spec(env.base, key="r", protocol="responses", model=FAILED_SHAPE)], {}
    )
    try:
        with pytest.raises(StreamAborted, match="server_error"):
            await _complete(pool, "default")
    finally:
        await pool.aclose()


async def test_incomplete_maps_to_length(env: _Env) -> None:
    pool = Pool(
        [make_spec(env.base, key="r", protocol="responses", model=INCOMPLETE_SHAPE)], {}
    )
    try:
        result = await _complete(pool, "default")
    finally:
        await pool.aclose()
    assert result.finish_reason == "length"


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
async def test_truncated_stream_aborts(env: _Env, protocol: ProtocolName) -> None:
    pool = Pool(
        [make_spec(env.base, key="x", protocol=protocol, model=TRUNCATE_SHAPE)], {}
    )
    try:
        with pytest.raises(StreamAborted) as info:
            await _complete(pool, "default")
    finally:
        await pool.aclose()
    partial = info.value.partial
    assert partial.text == EXPECTED_TEXT  # 已经下发的部分留在异常里
    if protocol == "anthropic":
        # anthropic 的用量在 message_start 就报, 所以截断流也有
        assert partial.usage is not None


async def test_auth_failure_disables_endpoint_and_fails_over(env: _Env) -> None:
    specs = [
        make_spec(env.base, key="bad", protocol="chat", model=UNAUTHORIZED_SHAPE),
        make_spec(env.base, key="good", protocol="chat"),
    ]
    pool = Pool(specs, {"chat": ["bad", "good"]})
    try:
        first = await _complete(pool, "chat")
        second = await _complete(pool, "chat")
    finally:
        await pool.aclose()

    assert first.endpoint_id == "good"
    assert second.endpoint_id == "good"
    # 鉴权失败之后不该再被选中
    assert [c.body["model"] for c in env.captured].count(UNAUTHORIZED_SHAPE) == 1


async def test_rate_limit_cools_down_and_fails_over(env: _Env) -> None:
    specs = [
        make_spec(env.base, key="slow", protocol="chat", model=RATELIMIT_SHAPE),
        make_spec(env.base, key="good", protocol="chat"),
    ]
    pool = Pool(specs, {"chat": ["slow", "good"]})
    try:
        first = await _complete(pool, "chat")
        second = await _complete(pool, "chat")
    finally:
        await pool.aclose()

    assert first.endpoint_id == "good"
    assert second.endpoint_id == "good"
    # 冷却期内不再打它
    assert [c.body["model"] for c in env.captured].count(RATELIMIT_SHAPE) == 1


async def test_capability_rejection_never_reaches_the_endpoint(env: _Env) -> None:
    spec = make_spec(env.base, key="c", protocol="chat")
    spec = EndpointSpec(
        id=spec.id,
        protocol=spec.protocol,
        base_url=spec.base_url,
        model=spec.model,
        api_key=spec.api_key,
        quirks=Quirks(supports_json_schema=False),
    )
    pool = Pool([spec], {})
    request = CompletionRequest(
        messages=(Message.user("给个 JSON"),),
        json_schema={"type": "object", "properties": {}},
    )
    try:
        with pytest.raises(LLMConfigError, match="JSON Schema"):
            await pool.complete(request)
    finally:
        await pool.aclose()
    assert env.captured == []


async def test_headers_carry_identity_and_session(env: _Env) -> None:
    spec = make_spec(
        env.base,
        key="c",
        protocol="chat",
        session_header="x-opencode-session",
    )
    pool = Pool([spec], {})
    try:
        await pool.complete(make_request(), session_id="session-1")
        await pool.complete(make_request(), session_id="session-1")
    finally:
        await pool.aclose()

    headers = [c.headers for c in env.captured]
    assert headers[0]["user-agent"] == DEFAULT_USER_AGENT
    assert headers[0]["x-opencode-session"] == "session-1"
    # 一次逻辑请求一个幂等键, 两次请求的键必须不同
    assert headers[0]["idempotency-key"] != headers[1]["idempotency-key"]


async def test_unknown_alias_is_rejected(env: _Env) -> None:
    pool = Pool([make_spec(env.base, key="c", protocol="chat")], {"chat": ["c"]})
    try:
        with pytest.raises(LLMConfigError, match="别名"):
            await _complete(pool, "nope")
    finally:
        await pool.aclose()
