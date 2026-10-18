"""精读与事实核查: ``.读`` 读一条链接或长文, ``.核`` 核一个说法

这里只做: 配置与端点池初始化、群与冷却的闸门、把事件翻译成一次 agent 调用、发送结果。
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from lemony_llm_provider import Agent, LLMError, LLMSettings, Pool
from lemony_onebot_utils.forward import ForwardBuilder, Sender
from lemony_settings import get_secret, require
from lemony_utils.help import Command, register_help
from melobot import PluginPlanner, get_bot
from melobot.handle import on_command
from melobot.protocols.onebot.v11 import Adapter, GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import TextSegment

from .prompts import CHECK_PROMPT, READ_PROMPT
from .settings import ReadCheckSettings
from .tools import WebTools, build_read_question, is_http_url
from .webapi import DeepseekTools, ToolsApiError

PLUGIN_IDENTIFIER = "readcheck"
LLM_IDENTIFIER = "llm"
CREDENTIAL_KEY = "readcheck.tools.api_key"

logger = logging.getLogger(__name__)
bot = get_bot()
plugin = PluginPlanner("0.1.0")
cfgloader = require(
    model=ReadCheckSettings, identifier=PLUGIN_IDENTIFIER, auto_load=False
)

register_help(
    PLUGIN_IDENTIFIER,
    title="精读与核查",
    summary="读一条链接或长文, 或者核查一个说法的真伪",
    commands=[
        Command(".读 <链接|正文>", "精读: 结论、三个要点、值得注意的地方"),
        Command(".核 <说法>", "事实核查: 逐条给结论、依据与来源日期"),
    ],
)


@dataclass
class _State:
    ready: bool = False
    error: str = ""
    pool: Pool | None = None
    api: DeepseekTools | None = None
    last_use: dict[int, float] = field(default_factory=dict)


state = _State()


@plugin.on_ready
async def _() -> None:
    # melobot 会吞掉 hook 里的异常, 失败只记日志, 让 handler 放弃
    try:
        await cfgloader.load_async()
        settings = cfgloader.value
        llm = require(model=LLMSettings, identifier=LLM_IDENTIFIER)
        await llm.load_async()
        state.pool = Pool.from_settings(llm.value)
        key = get_secret(settings.api_key_ref)
        if not key:
            raise RuntimeError(
                f"取不到联网接口的凭据 {settings.api_key_ref}; "
                "写进 credentials.json 或设置对应的环境变量"
            )
        state.api = DeepseekTools(settings.base_url, key)
        state.ready = True
    except Exception as exc:
        state.error = str(exc)
        logger.exception("readcheck 初始化失败, 插件将不响应")


@bot.on_stopped
async def _() -> None:
    if state.pool is not None:
        await state.pool.aclose()
        state.pool = None
    if state.api is not None:
        await state.api.aclose()
        state.api = None


def _argument_of(event: GroupMessageEvent, *names: str) -> str:
    text = (event.text or "").strip()
    pattern = rf"^[.。]\s*(?:{'|'.join(names)})\s*"
    return re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()


async def _gate(event: GroupMessageEvent, adapter: Adapter) -> bool:
    if not state.ready or state.pool is None or state.api is None:
        reason = state.error or "还在初始化"
        await adapter.send_reply(TextSegment(f"精读与核查暂时不可用: {reason}"))
        return False
    settings = cfgloader.value
    if settings.enabled_groups and event.group_id not in settings.enabled_groups:
        await adapter.send_reply(TextSegment("这个群没有开启精读与核查"))
        return False
    now = time.monotonic()
    last = state.last_use.get(event.group_id, 0.0)
    remain = settings.cooldown_seconds - (now - last)
    if remain > 0:
        await adapter.send_reply(TextSegment(f"刚用过, {int(remain) + 1} 秒后再来"))
        return False
    state.last_use[event.group_id] = now
    return True


async def _ask(
    event: GroupMessageEvent, question: str, *, system_prompt: str
) -> tuple[str, str]:
    """返回 (答案, 出错说明); 出错时答案为空格说明非空"""
    if state.pool is None or state.api is None:
        return "", "还没准备好"
    settings = cfgloader.value
    tz = ZoneInfo(settings.timezone)
    tools = WebTools(
        state.api,
        search_count=settings.search_count,
        max_fetch_chars=settings.max_fetch_chars,
    )
    agent = Agent(
        state.pool.complete,
        tools,
        alias=settings.alias,
        max_rounds=settings.max_rounds,
        max_tokens=settings.max_tokens,
        system_prompt=system_prompt,
        context=f"现在是 {datetime.now(tz).isoformat(timespec='minutes')}。",
        session_id=f"readcheck:{event.group_id}",
    )
    try:
        answer = await agent.ask(question)
    except LLMError as exc:
        logger.warning("精读与核查调用失败 [%s]: %s", exc.kind, exc)
        return "", f"模型暂时不可用: {exc.kind}"
    except Exception:
        logger.exception("精读与核查出现未预期错误")
        return "", "查的时候出错了, 稍后再试"
    logger.info(
        "精读与核查完成: 群 %s, 轮数 %s, 工具调用 %s, 长度 %s",
        event.group_id,
        answer.rounds,
        answer.tool_calls,
        len(answer.text),
    )
    return answer.text, ""


async def _send(event: GroupMessageEvent, adapter: Adapter, text: str) -> None:
    if len(text) <= cfgloader.value.max_answer_chars:
        await adapter.send_reply(TextSegment(text))
        return
    builder = ForwardBuilder(Sender.of_event(event))
    builder.text(text)
    await builder.send(adapter)


async def _fetch_article(url: str) -> str:
    """用户只给链接时, 先抓一次正文, 失败就让模型自己去抓"""
    if state.api is None:
        return ""
    try:
        page = await state.api.fetch(url)
    except ToolsApiError as exc:
        logger.warning("预抓取失败, 交给模型再试: %s", exc)
        return ""
    return f"标题: {page.title}\n正文:\n{page.content}"


@plugin.use
@on_command(".", " ", ["读", "read"])
async def read_link(event: GroupMessageEvent, adapter: Adapter) -> None:
    argument = _argument_of(event, "读", "read")
    if not argument:
        await adapter.send_reply(TextSegment("用法: .读 <链接 或 正文>"))
        return
    if not await _gate(event, adapter):
        return
    article = await _fetch_article(argument) if is_http_url(argument) else ""
    question = build_read_question(argument, article, cfgloader.value.max_input_chars)
    text, problem = await _ask(event, question, system_prompt=READ_PROMPT)
    if problem:
        await adapter.send_reply(TextSegment(problem))
        return
    await _send(event, adapter, text)


@plugin.use
@on_command(".", " ", ["核", "check"])
async def check_claim(event: GroupMessageEvent, adapter: Adapter) -> None:
    claim = _argument_of(event, "核", "check")
    if not claim:
        await adapter.send_reply(TextSegment("用法: .核 <要核查的说法>"))
        return
    if not await _gate(event, adapter):
        return
    text, problem = await _ask(
        event, f"请核查这个说法: {claim}", system_prompt=CHECK_PROMPT
    )
    if problem:
        await adapter.send_reply(TextSegment(problem))
        return
    await _send(event, adapter, text)


def _now_local() -> datetime:
    return datetime.now(UTC).astimezone(ZoneInfo(cfgloader.value.timezone))
