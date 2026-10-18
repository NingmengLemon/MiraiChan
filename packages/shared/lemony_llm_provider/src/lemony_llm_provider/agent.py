"""通用的工具调用循环

一次提问跑成"模型挑工具 -> 我们执行 -> 结果回填 -> 再问", 直到模型给出不带工具调用的回答,
或者用完轮数再让它按已有材料收尾。工具与模型调用都由调用方注入, 这里不关心工具是什么。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .client import Completion
from .models import CompletionRequest, Message, ToolSpec

__all__ = ["Agent", "AgentAnswer", "CompleteFn", "Toolbox"]

logger = logging.getLogger(__name__)

#: 单次 complete 的签名, 便于测试时换成假实现
CompleteFn = Callable[..., Awaitable[Completion]]


class Toolbox(Protocol):
    """agent 只要求这两样: 工具定义, 以及按名字执行"""

    @property
    def specs(self) -> Sequence[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, object]) -> str: ...


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    text: str
    rounds: int
    tool_calls: int
    hit_round_limit: bool = False


class Agent:
    def __init__(
        self,
        complete: CompleteFn,
        toolbox: Toolbox,
        *,
        alias: str | None = None,
        max_rounds: int = 4,
        max_tokens: int = 2048,
        system_prompt: str = "",
        context: str = "",
        session_id: str | None = None,
    ) -> None:
        self._complete = complete
        self._tools = toolbox
        self._alias = alias
        self._max_rounds = max(1, max_rounds)
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt + (f"\n\n{context}" if context else "")
        self._session_id = session_id

    @property
    def specs(self) -> Sequence[ToolSpec]:
        return self._tools.specs

    async def _call(
        self,
        messages: list[Message],
        *,
        with_tools: bool,
        max_tokens: int | None = None,
    ) -> Completion:
        request = CompletionRequest(
            system=self._system_prompt,
            messages=tuple(messages),
            tools=tuple(self.specs) if with_tools else (),
            tool_choice="auto" if with_tools else None,
            max_tokens=max_tokens or self._max_tokens,
        )
        return await self._complete(
            request, alias=self._alias, session_id=self._session_id
        )

    async def ask(self, question: str) -> AgentAnswer:
        messages: list[Message] = [Message.user(question)]
        used = 0
        budget = self._max_tokens
        retried = False
        for round_index in range(1, self._max_rounds + 1):
            result = await self._call(messages, with_tools=True, max_tokens=budget)
            if not result.tool_calls:
                # 思考模型把预算全花在思维链上时正文会是空的, 加一次预算再问
                if (
                    not result.text.strip()
                    and result.finish_reason == "length"
                    and not retried
                ):
                    retried = True
                    budget = min(self._max_tokens * 2, 8192)
                    logger.debug("回答被截断且正文为空, 把预算提到 %s 重试", budget)
                    continue
                return AgentAnswer(
                    text=result.text.strip(), rounds=round_index, tool_calls=used
                )
            # 带思考的模型要求把 reasoning / signature 一并回传, 否则下一轮会 400
            messages.append(
                Message.assistant(
                    result.text,
                    *result.tool_calls,
                    reasoning=result.reasoning or None,
                    signature=result.signature or None,
                )
            )
            for call in result.tool_calls:
                used += 1
                messages.append(
                    Message.tool_result(
                        call.id, await self._dispatch(call.name, call.arguments)
                    )
                )

        logger.debug("agent 达到轮数上限 %s, 收尾", self._max_rounds)
        final = await self._call(messages, with_tools=False, max_tokens=budget)
        return AgentAnswer(
            text=final.text.strip(),
            rounds=self._max_rounds,
            tool_calls=used,
            hit_round_limit=True,
        )

    async def _dispatch(self, name: str, arguments: str) -> str:
        try:
            parsed = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "工具参数不是合法 JSON"
        if not isinstance(parsed, dict):
            return "工具参数必须是对象"
        return await self._tools.call(name, parsed)
