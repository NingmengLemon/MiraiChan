"""最小 agent 循环: 模型决定调哪个工具, 我们把结果喂回去, 直到它给出答案"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from lemony_llm_provider import Completion, CompletionRequest, Message

logger = logging.getLogger(__name__)

__all__ = ["SYSTEM_PROMPT", "Answer", "Historian"]

#: 单次 complete 的签名, 便于测试时换成假实现
CompleteFn = Callable[..., Awaitable[Completion]]

SYSTEM_PROMPT = """你是这个群聊的记录员, 只能依据工具返回的群聊记录回答。

- 先想清楚要查什么, 再用工具: 不知道谁提过就用 search_history, 想知道谁最活跃就用 speaker_stats,
  想给某个人定性就用 speaker_messages。
- 回答必须带出处: 引用时写出"[月-日 时:分] 昵称: 原话片段", 不要编造没有出现在工具结果里的内容。
- 工具没查到就说没查到, 并给出可以换个说法的建议, 不要凭空推测。
- 用中文, 直接给结论, 不要复述提问。篇幅尽量短, 除非用户要求详细。"""


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    rounds: int
    tool_calls: int
    hit_round_limit: bool = False


class Historian:
    """把一次提问跑成"调工具 -> 回填 -> 再问"的循环"""

    def __init__(
        self,
        complete: CompleteFn,
        tools: object,
        *,
        alias: str | None = None,
        max_rounds: int = 4,
        max_tokens: int = 2048,
        system_prompt: str = SYSTEM_PROMPT,
        session_id: str | None = None,
    ) -> None:
        self._complete = complete
        self._tools = tools
        self._alias = alias
        self._max_rounds = max(1, max_rounds)
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._session_id = session_id

    @property
    def specs(self):
        return getattr(self._tools, "specs", ())

    async def _call(self, messages: list[Message], *, with_tools: bool) -> Completion:
        request = CompletionRequest(
            system=self._system_prompt,
            messages=tuple(messages),
            tools=self.specs if with_tools else (),
            tool_choice="auto" if with_tools else None,
            max_tokens=self._max_tokens,
        )
        return await self._complete(
            request, alias=self._alias, session_id=self._session_id
        )

    async def ask(self, question: str) -> Answer:
        messages: list[Message] = [Message.user(question)]
        used = 0
        for round_index in range(1, self._max_rounds + 1):
            result = await self._call(messages, with_tools=True)
            if not result.tool_calls:
                return Answer(
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
                output = await self._dispatch(call.name, call.arguments)
                messages.append(Message.tool_result(call.id, output))

        # 轮数用完: 不再给工具, 让它按已有材料收尾
        logger.debug("群史问答达到轮数上限 %s, 收尾", self._max_rounds)
        final = await self._call(messages, with_tools=False)
        return Answer(
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
        call = getattr(self._tools, "call", None)
        if call is None:
            return "没有可用的工具"
        return await call(name, parsed)
