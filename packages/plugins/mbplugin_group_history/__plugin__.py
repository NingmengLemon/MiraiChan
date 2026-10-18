"""群史问答: 在群里问一句, 让模型带着工具去翻记录

这里只做: 配置与端点池初始化、群与冷却的闸门、把事件翻译成一次 agent 调用、发送结果。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from lemony_llm_provider import LLMError, LLMSettings, Pool
from lemony_onebot_utils.forward import ForwardBuilder, Sender
from lemony_settings import require
from lemony_utils.help import Command, register_help
from melobot import PluginPlanner, get_bot
from melobot.exceptions import PluginIpcError
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import TextSegment

from .agent import SYSTEM_PROMPT, Answer, Historian
from .history import GroupRef
from .settings import GroupHistorySettings
from .tools import HistoryTools, ToolContext

PLUGIN_IDENTIFIER = "group_history"
LLM_IDENTIFIER = "llm"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner("0.1.0")
cfgloader = require(
    model=GroupHistorySettings, identifier=PLUGIN_IDENTIFIER, auto_load=False
)

PROFILE_PROMPT = (
    SYSTEM_PROMPT
    + "\n\n这次任务是为某位群友画一张「人物画像」: 先看他的发言, 再总结关注点、说话风格、口头禅与"
    "活跃时间段。语气可以俏皮, 但每一条结论都要落在记录上。"
)


@dataclass
class _State:
    ready: bool = False
    error: str = ""
    pool: Pool | None = None
    # 群号 -> 上一次提问的 monotonic 时间
    last_ask: dict[int, float] = field(default_factory=dict)


state = _State()

register_help(
    PLUGIN_IDENTIFIER,
    title="群史问答",
    summary="让模型带着工具翻群聊记录, 回答问题或给群友画画像",
    commands=[
        Command(".问 <问题>", "检索群历史消息后回答, 回答里会带发言人与时间"),
        Command(".画像 <群名片>", "按历史发言给某位群友画一张人物画像"),
    ],
)


def _recorder():
    try:
        return bot.get_share("mbplugin_recorder", "recorder_service").get()
    except PluginIpcError:
        return None


@plugin.on_ready
async def _() -> None:
    # melobot 会吞掉 hook 里的异常, 失败只记日志, 让 handler 放弃
    try:
        await cfgloader.load_async()
        llm = require(model=LLMSettings, identifier=LLM_IDENTIFIER)
        await llm.load_async()
        state.pool = Pool.from_settings(llm.value)
        state.ready = True
    except Exception as exc:
        state.error = str(exc)
        logger.exception("group_history 初始化失败, 插件将不响应")


@bot.on_stopped
async def _() -> None:
    if state.pool is not None:
        await state.pool.aclose()
        state.pool = None


def _question_of(event: GroupMessageEvent, *names: str) -> str:
    text = (event.text or "").strip()
    pattern = rf"^[.。]\s*(?:{'|'.join(names)})\s*"
    return re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()


async def _gate(event: GroupMessageEvent, adapter: Adapter) -> bool:
    """初始化、群白名单与冷却, 任一项不过就回一句并放弃"""
    if not state.ready or state.pool is None:
        reason = state.error or "还在初始化"
        await adapter.send_reply(TextSegment(f"群史问答暂时不可用: {reason}"))
        return False
    settings = cfgloader.value
    if settings.enabled_groups and event.group_id not in settings.enabled_groups:
        await adapter.send_reply(TextSegment("这个群没有开启群史问答"))
        return False
    now = time.monotonic()
    last = state.last_ask.get(event.group_id, 0.0)
    remain = settings.cooldown_seconds - (now - last)
    if remain > 0:
        await adapter.send_reply(TextSegment(f"刚查过, {int(remain) + 1} 秒后再问"))
        return False
    state.last_ask[event.group_id] = now
    return True


def _session_factory(event: GroupMessageEvent):
    recorder = _recorder()
    if recorder is None:
        return None
    return recorder.get_session


async def _answer(
    event: GroupMessageEvent, question: str, *, system_prompt: str
) -> Answer | str:
    if state.pool is None:
        return "还没准备好"
    factory = _session_factory(event)
    if factory is None:
        return "记录器插件没加载, 查不了历史"
    settings = cfgloader.value
    tz = ZoneInfo(settings.timezone)
    context = ToolContext(
        ref=GroupRef(
            protocol=str(event.protocol),
            self_id=str(event.self_id),
            group_id=str(event.group_id),
        ),
        # 库里存 UTC, 比较一律用 UTC; 只有展示时间时才换成配置里的时区
        now=datetime.now(UTC),
        tz=tz,
        window_days=settings.window_days,
        max_window_days=settings.max_window_days,
        result_limit=settings.result_limit,
        max_tool_chars=settings.max_tool_chars,
    )
    historian = Historian(
        state.pool.complete,
        HistoryTools(factory, context),
        alias=settings.alias,
        max_rounds=settings.max_rounds,
        max_tokens=settings.max_tokens,
        system_prompt=system_prompt,
        # 同一个群用同一个会话标识, 依赖前缀缓存的端点可以少算一点
        session_id=f"group-history:{event.group_id}",
        # 给模型看的当前时间是本地时间, 它才能把「昨晚」落到窗口上
        now=datetime.now(tz),
    )
    return await historian.ask(question)


async def _send(event: GroupMessageEvent, adapter: Adapter, text: str) -> None:
    if not text:
        await adapter.send_reply(TextSegment("模型没有给出内容"))
        return
    if len(text) <= cfgloader.value.max_answer_chars:
        await adapter.send_reply(TextSegment(text))
        return
    # 长回答转合并转发, 免得刷屏
    builder = ForwardBuilder(Sender.of_event(event))
    builder.text(text)
    await builder.send(adapter)


async def _run(
    event: GroupMessageEvent,
    adapter: Adapter,
    question: str,
    *,
    system_prompt: str,
    empty_hint: str,
) -> None:
    if not question:
        await adapter.send_reply(TextSegment(empty_hint))
        return
    if not await _gate(event, adapter):
        return
    try:
        answer = await _answer(event, question, system_prompt=system_prompt)
    except LLMError as exc:
        logger.warning("群史问答调用失败 [%s]: %s", exc.kind, exc)
        await adapter.send_reply(TextSegment(f"模型暂时不可用: {exc.kind}"))
        return
    except Exception:
        logger.exception("群史问答出现未预期错误")
        await adapter.send_reply(TextSegment("查的时候出错了, 稍后再试"))
        return
    if isinstance(answer, str):
        await adapter.send_reply(TextSegment(answer))
        return
    logger.info(
        "群史问答完成: 群 %s, 轮数 %s, 工具调用 %s, 长度 %s",
        event.group_id,
        answer.rounds,
        answer.tool_calls,
        len(answer.text),
    )
    await _send(event, adapter, answer.text)


@plugin.use
@on_command(".", " ", ["问", "ask"])
async def ask_history(event: GroupMessageEvent, adapter: Adapter) -> None:
    await _run(
        event,
        adapter,
        _question_of(event, "问", "ask"),
        system_prompt=SYSTEM_PROMPT,
        empty_hint="用法: .问 <想查什么>",
    )


@plugin.use
@on_command(".", " ", ["画像", "profile"])
async def ask_profile(event: GroupMessageEvent, adapter: Adapter) -> None:
    who = _question_of(event, "画像", "profile")
    await _run(
        event,
        adapter,
        f"给群友 {who} 画一张人物画像" if who else "",
        system_prompt=PROFILE_PROMPT,
        empty_hint="用法: .画像 <群名片>",
    )
