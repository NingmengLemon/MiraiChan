"""群史问答的提示词与 agent 组装

循环本身在 ``lemony_llm_provider.agent`` 里, 这里只提供这个场景的提示词与当前时间。
"""

from __future__ import annotations

from datetime import datetime

from lemony_llm_provider import Agent, AgentAnswer, CompleteFn, Toolbox

__all__ = ["SYSTEM_PROMPT", "Answer", "Historian"]

Answer = AgentAnswer

SYSTEM_PROMPT = """你是这个群聊的记录员, 只能依据工具返回的群聊记录回答。

- 先想清楚要查什么, 再用工具: 不知道谁提过就用 search_history, 想知道谁最活跃就用 speaker_stats,
  想给某个人定性就用 speaker_messages。
- 回答必须带出处: 引用时写出"[月-日 时:分] 昵称: 原话片段", 不要编造没有出现在工具结果里的内容。
- 工具没查到就说没查到, 并给出可以换个说法的建议, 不要凭空推测。
- 用中文, 直接给结论, 不要复述提问。篇幅尽量短, 除非用户要求详细。"""


def Historian(
    complete: CompleteFn,
    toolbox: Toolbox,
    *,
    alias: str | None = None,
    max_rounds: int = 4,
    max_tokens: int = 2048,
    system_prompt: str = SYSTEM_PROMPT,
    session_id: str | None = None,
    now: datetime | None = None,
) -> Agent:
    # 相对时间(比如「昨晚」)要靠当前时间才能落到具体窗口上
    context = f"现在是 {now.isoformat(timespec='minutes')}。" if now else ""
    return Agent(
        complete,
        toolbox,
        alias=alias,
        max_rounds=max_rounds,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        context=context,
        session_id=session_id,
    )
