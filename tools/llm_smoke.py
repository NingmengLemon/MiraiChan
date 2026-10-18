"""对真实端点跑一遍最小 smoke: 三套协议各发一次, 校验归一化结果

需要 OPENCODE_GO_API_KEY 与 DEEPSEEK_API_KEY (放在环境变量或 .env 里),
用 `uv run --env-file .env python tools/llm_smoke.py` 运行。
脚本不打印任何凭据, 也不把请求头写进日志。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass
from typing import Literal

from lemony_llm_provider import (
    CompletionRequest,
    EndpointSpec,
    ImagePart,
    LLMError,
    Message,
    Pool,
    Reasoning,
    ToolSpec,
    Usage,
    resolve_quirks,
)

TOOLS = (
    ToolSpec(
        name="get_time",
        description="查询某个时区的当前时间",
        parameters={
            "type": "object",
            "properties": {
                "tz": {"type": "string", "description": "IANA 时区, 例如 Asia/Tokyo"}
            },
            "required": ["tz"],
        },
    ),
)

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "temperature_c": {"type": "number"}},
    "required": ["city", "temperature_c"],
    "additionalProperties": False,
}


ProtocolName = Literal["chat", "responses", "anthropic"]


@dataclass(frozen=True)
class Target:
    key: str
    protocol: ProtocolName
    base_url: str
    model: str
    quirks: str
    env: str
    # OpenCode Go 要求客户端自报会话, 以便它们做路由与缓存
    session_header: str | None = None
    supports_json: bool = True


TARGETS = (
    Target(
        key="go-deepseek-chat",
        protocol="chat",
        base_url="https://opencode.ai/inference/go/openai/v1",
        model="deepseek-v4.1-flash",
        # quirks 跟模型走而不是跟中转走: DeepSeek 在 Go 上一样不认 json_schema
        quirks="deepseek_chat",
        supports_json=False,
        env="OPENCODE_GO_API_KEY",
        session_header="x-opencode-session",
    ),
    Target(
        key="go-gpt-responses",
        protocol="responses",
        base_url="https://opencode.ai/inference/go/openai/v1",
        model="gpt-6-luna",
        quirks="openai_responses",
        env="OPENCODE_GO_API_KEY",
        session_header="x-opencode-session",
    ),
    Target(
        key="go-claude-anthropic",
        protocol="anthropic",
        base_url="https://opencode.ai/inference/go/anthropic",
        model="claude-haiku-5-5",
        quirks="anthropic",
        env="OPENCODE_GO_API_KEY",
        session_header="x-opencode-session",
    ),
    Target(
        key="deepseek-official-chat",
        protocol="chat",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        quirks="deepseek_chat",
        supports_json=False,
        env="DEEPSEEK_API_KEY",
    ),
    Target(
        key="deepseek-official-responses",
        protocol="responses",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        quirks="deepseek_responses",
        env="DEEPSEEK_API_KEY",
    ),
)


def _spec(target: Target, key: str) -> EndpointSpec:
    return EndpointSpec(
        id=target.key,
        protocol=target.protocol,
        base_url=target.base_url,
        model=target.model,
        api_key=key,
        quirks=resolve_quirks(target.quirks),
        session_header=target.session_header,
        timeout=120.0,
    )


def red_square_png() -> bytes:
    """临时生成一张纯色小图, 用来验证图片输入这条路"""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (16, 16), (220, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _fmt_usage(usage: Usage | None) -> str:
    if usage is None:
        return "usage=None"
    return (
        f"in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_read={usage.cached_input_tokens} cache_write={usage.cache_write_input_tokens} "
        f"reasoning={usage.reasoning_tokens}"
    )


async def _plain(pool: Pool) -> None:
    request = CompletionRequest(
        system="你是一个简洁的助手, 回答控制在两句话以内.",
        messages=(Message.user("用一句话说明这次请求走的是哪个协议栈."),),
        max_tokens=1024,
        reasoning=Reasoning(effort="low"),
    )
    began = time.monotonic()
    result = await pool.complete(request, session_id="smoke-plain")
    elapsed = time.monotonic() - began
    print(
        f"  plain    ok  {elapsed:5.2f}s  finish={result.finish_reason}  {_fmt_usage(result.usage)}"
    )
    print(f"           text={result.text[:80]!r}")
    if result.reasoning:
        print(f"           reasoning={len(result.reasoning)} chars")
    if result.signature:
        print(f"           signature={len(result.signature)} chars")


async def _tool_round(
    pool: Pool, *, reasoning: Reasoning | None = None, max_tokens: int = 512
) -> None:
    request = CompletionRequest(
        system="你可以调用工具. 需要真实数据时必须调用.",
        messages=(
            Message.user("东京现在几点? 用 get_time 工具查, 时区写 Asia/Tokyo."),
        ),
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=max_tokens,
        reasoning=reasoning or Reasoning(effort="low"),
    )
    result = await pool.complete(request, session_id="smoke-tool")
    calls = ", ".join(f"{c.name}{c.arguments}" for c in result.tool_calls) or "(无)"
    print(f"  tool     ok  finish={result.finish_reason}  {_fmt_usage(result.usage)}")
    print(f"           tool_calls={calls}")
    if result.signature:
        print(f"           signature={len(result.signature)} chars")
    if result.tool_calls:
        # 回填一次工具结果, 验证多轮拼接
        follow = CompletionRequest(
            system=request.system,
            messages=(
                *request.messages,
                Message.assistant(
                    result.text,
                    *result.tool_calls,
                    reasoning=result.reasoning or None,
                    signature=result.signature or None,
                ),
                *(
                    Message.tool_result(call.id, '{"time":"2026-10-18T12:30:00+09:00"}')
                    for call in result.tool_calls
                ),
            ),
            tools=TOOLS,
            max_tokens=512,
        )
        second = await pool.complete(follow, session_id="smoke-tool")
        print(
            f"  followup ok  finish={second.finish_reason}  text={second.text[:60]!r}"
        )


async def _structured(pool: Pool) -> None:
    request = CompletionRequest(
        messages=(Message.user("杭州现在 21 度, 请按 schema 输出."),),
        json_schema=SCHEMA,
        json_schema_name="weather",
        max_tokens=256,
    )
    result = await pool.complete(request, session_id="smoke-json")
    print(f"  json     ok  finish={result.finish_reason}  text={result.text[:100]!r}")


async def _image_round(pool: Pool) -> None:
    image = ImagePart(data=red_square_png(), media_type="image/png")
    request = CompletionRequest(
        messages=(Message.user("这张图主要是什么颜色? 用一个词回答.", image),),
        # 思考模型会先花掉一大截预算, 给少了就只剩 finish=length
        max_tokens=1024,
    )
    result = await pool.complete(request, session_id="smoke-image")
    print(f"  image    ok  finish={result.finish_reason}  text={result.text[:60]!r}")


async def run(target: Target, *, with_structured: bool) -> list[str]:
    key = os.environ.get(target.env)
    if not key:
        return [f"{target.key}: 环境变量 {target.env} 没有设置"]
    print(f"\n== {target.key} ({target.protocol} / {target.model}) ==")
    pool = Pool([_spec(target, key)], {})
    problems: list[str] = []
    try:
        for name, call in (
            ("plain", _plain(pool)),
            ("image", _image_round(pool)),
            (
                "tool",
                _tool_round(
                    pool,
                    # Claude 用 adaptive 思考加 effort; 这一步会验证 signature 能否回传
                    reasoning=(
                        Reasoning(effort="high")
                        if target.protocol == "anthropic"
                        else None
                    ),
                    max_tokens=4096 if target.protocol == "anthropic" else 512,
                ),
            ),
        ):
            try:
                await call
            except LLMError as exc:
                problems.append(f"{target.key}: {name} 失败 [{exc.kind}] {exc}")
                print(f"  {name}  FAIL [{exc.kind}] {exc}")
        if with_structured:
            try:
                await _structured(pool)
            except LLMError as exc:
                problems.append(f"{target.key}: json 失败 [{exc.kind}] {exc}")
                print(f"  json     FAIL [{exc.kind}] {exc}")
    finally:
        await pool.aclose()
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="只跑指定的端点 key")
    parser.add_argument("--skip-json", action="store_true", help="跳过结构化输出那一轮")
    args = parser.parse_args()

    targets = [t for t in TARGETS if not args.only or t.key == args.only]
    if not targets:
        print(f"没有匹配的端点: {args.only}")
        return 2

    problems: list[str] = []
    for target in targets:
        problems.extend(
            await run(
                target, with_structured=not args.skip_json and target.supports_json
            )
        )

    print()
    if problems:
        print(f"{len(problems)} 项失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
