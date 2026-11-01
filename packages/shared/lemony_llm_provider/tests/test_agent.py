"""Agent 工具循环的回归测试: 预算与工具失败回填."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from lemony_llm_provider import (
    Agent,
    Completion,
    CompletionRequest,
    FinishReason,
    ToolCall,
    ToolSpec,
)


class _Toolbox:
    specs: Sequence[ToolSpec] = ()

    async def call(self, name: str, arguments: dict[str, object]) -> str:
        raise RuntimeError("boom")


def _completion(
    text: str = "",
    *,
    tool_calls: tuple[ToolCall, ...] = (),
    finish_reason: FinishReason = "stop",
) -> Completion:
    return Completion(
        text=text,
        reasoning="",
        signature="",
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=None,
        endpoint_id="e",
    )


@pytest.mark.asyncio
async def test_empty_length_answer_retries_with_a_larger_budget() -> None:
    requests: list[CompletionRequest] = []

    async def complete(request: CompletionRequest, **_: Any) -> Completion:
        requests.append(request)
        if len(requests) == 1:
            return _completion(finish_reason="length")
        return _completion("ok")

    agent = Agent(complete, _Toolbox(), max_tokens=2048)
    answer = await agent.ask("q")

    assert [request.max_tokens for request in requests] == [2048, 4096]
    assert answer.text == "ok"


@pytest.mark.asyncio
async def test_retry_budget_does_not_shrink_above_the_cap() -> None:
    requests: list[CompletionRequest] = []

    async def complete(request: CompletionRequest, **_: Any) -> Completion:
        requests.append(request)
        if len(requests) == 1:
            return _completion(finish_reason="length")
        return _completion("ok")

    agent = Agent(complete, _Toolbox(), max_tokens=10000)
    await agent.ask("q")

    assert [request.max_tokens for request in requests] == [10000, 10000]


@pytest.mark.asyncio
async def test_tool_exception_is_returned_to_the_model() -> None:
    requests: list[CompletionRequest] = []

    async def complete(request: CompletionRequest, **_: Any) -> Completion:
        requests.append(request)
        if len(requests) == 1:
            return _completion(
                tool_calls=(ToolCall("c1", "boom", "{}"),), finish_reason="tool_calls"
            )
        return _completion("done")

    agent = Agent(complete, _Toolbox())
    answer = await agent.ask("q")

    assert answer.text == "done"
    result = requests[1].messages[-1]
    assert result.is_error is True
    assert result.text() == "工具执行失败: RuntimeError"
