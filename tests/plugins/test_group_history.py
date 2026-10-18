"""群史问答: 查询层、工具层与 agent 循环

数据库用 recorder 的真实写入路径灌进 tmp_path, 所以查询跑在真正的表结构上。
agent 那部分注入了假的 complete, 不碰网络。
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from lemony_llm_provider import Completion, CompletionRequest, ToolCall
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from mbplugin_group_history.agent import Historian
from mbplugin_group_history.history import (
    GroupRef,
    find_conversation_id,
    search_messages,
    speaker_stats,
)
from mbplugin_group_history.tools import HistoryTools, ToolContext
from mbplugin_recorder.db.dto import (
    AccountInput,
    ConversationInput,
    IdentityInput,
    MessageSegmentInput,
    RecordedMessageInput,
)
from mbplugin_recorder.db.models import recorder_metadata
from mbplugin_recorder.db.operations import record_message
from mbplugin_recorder.service import RecorderService

PROTOCOL = "onebot-v11"
SELF_ID = "10000"
GROUP = "20000"
ALICE, BOB = "30001", "30002"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

# (message id, sender, text)
TIMELINE = [
    ("m1", ALICE, "周末去爬山吗"),
    ("m2", BOB, "加班, 去不了"),
    ("m3", ALICE, "那下周呢"),
    ("m4", BOB, "下周可以"),
    ("m5", SELF_ID, "收到"),
]


def _payload(mid: str, sender: str, text: str, at: datetime) -> RecordedMessageInput:
    account = AccountInput(protocol=PROTOCOL, self_id=SELF_ID)
    return RecordedMessageInput(
        account=account,
        conversation=ConversationInput(type="group", external_id=GROUP),
        sender=IdentityInput(
            protocol=PROTOCOL,
            namespace="user",
            external_id=sender,
            display_name=f"nick-{sender}",
            account=account,
        ),
        external_message_id=mid,
        sent_at=at,
        sender_conversation_name=f"card-{sender}",
        # 检索读的是 recorder 写入的 text_content, 不是 segment
        text_content=text,
        index_text=text,
        segments=[MessageSegmentInput(type="text", data={"text": text}, text=text)],
    )


@pytest_asyncio.fixture
async def service(tmp_path: Path) -> AsyncIterator[RecorderService]:
    db = SqliteDatabaseHelper(
        "recorder.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    await db.startup()
    async with db.get_session(style="sqlalchemy") as session:
        for index, (mid, sender, text) in enumerate(TIMELINE):
            await record_message(
                session, _payload(mid, sender, text, T0 + timedelta(minutes=index))
            )
    try:
        yield RecorderService(db)
    finally:
        await db.close()


def _ref() -> GroupRef:
    return GroupRef(protocol=PROTOCOL, self_id=SELF_ID, group_id=GROUP)


def _tools(service: RecorderService, tz: tzinfo = UTC) -> HistoryTools:
    context = ToolContext(
        ref=_ref(),
        now=T0 + timedelta(days=1),
        window_days=30,
        max_window_days=365,
        result_limit=20,
        max_tool_chars=3000,
        tz=tz,
    )
    return HistoryTools(lambda: service.get_session(), context)


@pytest.mark.asyncio
async def test_find_conversation(service: RecorderService) -> None:
    async with service.get_session() as session:
        conversation_id = await find_conversation_id(session, _ref())
        assert conversation_id is not None
        missing = await find_conversation_id(
            session, GroupRef(PROTOCOL, SELF_ID, "999999")
        )
        assert missing is None


@pytest.mark.asyncio
async def test_search_filters_and_order(service: RecorderService) -> None:
    async with service.get_session() as session:
        conversation_id = await find_conversation_id(session, _ref())
        assert conversation_id is not None
        hits = await search_messages(
            session,
            conversation_id,
            since=T0 - timedelta(days=1),
            keywords=("下周",),
            exclude_sender_external_ids=(SELF_ID,),
        )
    assert [hit.text for hit in hits] == ["下周可以", "那下周呢"]  # 新的在前
    assert hits[0].sender == "card-30002"


@pytest.mark.asyncio
async def test_speaker_filter(service: RecorderService) -> None:
    async with service.get_session() as session:
        conversation_id = await find_conversation_id(session, _ref())
        assert conversation_id is not None
        hits = await search_messages(
            session,
            conversation_id,
            since=T0 - timedelta(days=1),
            speaker="card-30001",
            exclude_sender_external_ids=(SELF_ID,),
        )
    assert {hit.text for hit in hits} == {"周末去爬山吗", "那下周呢"}


@pytest.mark.asyncio
async def test_speaker_stats_excludes_bot(service: RecorderService) -> None:
    async with service.get_session() as session:
        conversation_id = await find_conversation_id(session, _ref())
        assert conversation_id is not None
        stats = await speaker_stats(
            session,
            conversation_id,
            since=T0 - timedelta(days=1),
            exclude_sender_external_ids=(SELF_ID,),
        )
    # 条数相同时 SQLite 返回次序不稳定, 只比较集合
    assert sorted((item.sender, item.count) for item in stats) == [
        ("card-30001", 2),
        ("card-30002", 2),
    ]


@pytest.mark.asyncio
async def test_tool_formats_hits(service: RecorderService) -> None:
    tools = _tools(service)
    output = await tools.call("search_history", {"keywords": ["爬山"]})
    assert "card-30001" in output
    assert "周末去爬山吗" in output
    assert output.startswith("1. [")

    stats = await tools.call("speaker_stats", {})
    assert "共 4 条" in stats

    profile = await tools.call("speaker_messages", {"speaker": "30002"})
    assert "加班, 去不了" in profile


@pytest.mark.asyncio
async def test_tool_guards(service: RecorderService) -> None:
    tools = _tools(service)
    assert "至少给一个关键词" in await tools.call("search_history", {})
    assert "没有名为" in await tools.call("nope", {})
    assert "需要给出要查的发言者" in await tools.call("speaker_messages", {})


def _completion(text: str = "", calls: tuple[ToolCall, ...] = ()) -> Completion:
    return Completion(
        text=text,
        reasoning="",
        signature="",
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        usage=None,
        endpoint_id="test",
    )


async def test_timestamps_render_in_configured_timezone(
    service: RecorderService,
) -> None:
    from zoneinfo import ZoneInfo

    utc_output = await _tools(service).call("search_history", {"keywords": ["爬山"]})
    shanghai = await _tools(service, ZoneInfo("Asia/Shanghai")).call(
        "search_history", {"keywords": ["爬山"]}
    )
    # T0 是 12:00 UTC, 上海时间应当是 20:00
    assert "[10-01 12:00]" in utc_output
    assert "[10-01 20:00]" in shanghai


async def test_historian_tells_the_model_what_time_it_is(
    service: RecorderService,
) -> None:
    seen: list[CompletionRequest] = []

    async def fake(request: CompletionRequest, **_: object) -> Completion:
        seen.append(request)
        return _completion(text="好")

    when = datetime(2026, 10, 18, 9, 30, tzinfo=UTC)
    historian = Historian(fake, _tools(service), now=when)
    await historian.ask("昨晚聊了什么")
    assert "现在是 2026-10-18T09:30" in (seen[0].system or "")


async def test_agent_calls_tool_then_answers(service: RecorderService) -> None:
    recorded: list[CompletionRequest] = []
    replies = [
        _completion(
            calls=(
                ToolCall(
                    "call_1", "search_history", json.dumps({"keywords": ["爬山"]})
                ),
            )
        ),
        _completion(text="[10-01 12:00] card-30001: 周末去爬山吗"),
    ]

    async def fake_complete(request: CompletionRequest, **_: object) -> Completion:
        recorded.append(request)
        return replies[len(recorded) - 1]

    historian = Historian(
        fake_complete, _tools(service), alias="chat", max_rounds=3, session_id="t"
    )
    answer = await historian.ask("谁提过爬山?")
    assert answer.text == "[10-01 12:00] card-30001: 周末去爬山吗"
    assert answer.tool_calls == 1
    assert answer.rounds == 2
    # 第二轮必须把工具结果带回去
    second = recorded[1].messages[-1]
    assert second.role == "tool"
    assert second.tool_call_id == "call_1"
    assert "周末去爬山吗" in second.text()


async def test_agent_stops_at_round_limit(service: RecorderService) -> None:
    calls: list[CompletionRequest] = []

    async def always_tool(request: CompletionRequest, **_: object) -> Completion:
        calls.append(request)
        return _completion(calls=(ToolCall("call_x", "speaker_stats", "{}"),))

    historian = Historian(always_tool, _tools(service), max_rounds=2)
    answer = await historian.ask("谁最活跃?")
    assert answer.hit_round_limit is True
    assert answer.tool_calls == 2
    # 收尾那一次不再带工具
    assert calls[-1].tools == ()
    assert calls[-1].tool_choice is None


async def test_agent_reports_bad_arguments(service: RecorderService) -> None:
    seen: list[CompletionRequest] = []

    async def fake(request: CompletionRequest, **_: object) -> Completion:
        seen.append(request)
        if len(seen) == 1:
            return _completion(calls=(ToolCall("c1", "search_history", "not json"),))
        return _completion(text="好")

    historian = Historian(fake, _tools(service), max_rounds=2)
    await historian.ask("随便问问")
    assert "不是合法 JSON" in seen[1].messages[-1].text()
