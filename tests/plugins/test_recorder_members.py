"""recorder 成员状态机: 进出会话、禁言与角色变更如何影响活跃状态.

回归点:

- 每条消息都把 ``active_since`` 改写成消息时间, 入群时间被冲掉。
- 禁言 (OneBot 的 ``group_ban`` 是禁言而非踢出) 与角色变更被当成"离开": 成员被标成不活跃,
  之后的 ``admin_set`` / ``lift_ban`` 又把活跃起点改成当时的时间。
- 重新加入时旧的 ``inactive_since`` 没被清掉, 同一行既"已离开"又"活跃"。
"""

import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from mbplugin_recorder.db.dto import (
    AccountInput,
    ConversationInput,
    IdentityInput,
    MemberEventInput,
    RecordedMessageInput,
)
from mbplugin_recorder.db.models import ConversationMember, recorder_metadata
from mbplugin_recorder.db.operations import record_member_event, record_message
from mbplugin_recorder.migration import migrate
from sqlalchemy import select

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[SqliteDatabaseHelper]:
    helper = SqliteDatabaseHelper(
        "r.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    await helper.startup(prepare=migrate)
    try:
        yield helper
    finally:
        await helper.close()


def _account() -> AccountInput:
    return AccountInput(protocol="p", self_id="1")


def _conversation() -> ConversationInput:
    return ConversationInput(type="group", external_id="2")


def _identity() -> IdentityInput:
    return IdentityInput(
        protocol="p", namespace="user", external_id="3", account=_account()
    )


def _member_event(
    event_type: str, *, at: datetime, role: str | None = None
) -> MemberEventInput:
    return MemberEventInput(
        account=_account(),
        conversation=_conversation(),
        identity=_identity(),
        event_type=event_type,
        happened_at=at,
        role=role,
    )


def _message(mid: str, *, sent_at: datetime) -> RecordedMessageInput:
    return RecordedMessageInput(
        account=_account(),
        conversation=_conversation(),
        sender=_identity(),
        external_message_id=mid,
        sent_at=sent_at,
        segments=[],
    )


async def _member(db: SqliteDatabaseHelper) -> ConversationMember:
    async with db.get_session(style="sqlalchemy") as s:
        return (await s.execute(select(ConversationMember))).scalar_one()


@pytest.mark.asyncio
async def test_message_does_not_overwrite_join_time(db: SqliteDatabaseHelper) -> None:
    """消息只证明成员此刻活跃, 不能把入群时间改写成发言时间."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("approve", at=T0))
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _message("m1", sent_at=T1))
        await record_message(s, _message("m2", sent_at=T2))

    member = await _member(db)
    assert member.is_active is True
    assert member.active_since == T0
    assert member.inactive_since is None


@pytest.mark.asyncio
async def test_first_seen_message_sets_active_since(db: SqliteDatabaseHelper) -> None:
    """没有入群记录时, 首次见到该成员的时间就是活跃起点."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _message("m1", sent_at=T1))

    member = await _member(db)
    assert member.is_active is True
    assert member.active_since == T1


@pytest.mark.asyncio
async def test_ban_and_lift_ban_do_not_change_membership(
    db: SqliteDatabaseHelper,
) -> None:
    """禁言 (group_ban) 不是退群, 解禁也不是重新加入."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("approve", at=T0))
        await record_member_event(s, _member_event("ban", at=T1))

    member = await _member(db)
    assert member.is_active is True
    assert member.active_since == T0
    assert member.inactive_since is None

    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("lift_ban", at=T2))

    member = await _member(db)
    assert member.is_active is True
    assert member.active_since == T0
    assert member.inactive_since is None


@pytest.mark.asyncio
async def test_admin_unset_keeps_member_active(db: SqliteDatabaseHelper) -> None:
    """撤掉管理员不等于退群, 也不能把活跃起点改成撤职时间."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("approve", at=T0, role="member"))
        await record_member_event(s, _member_event("admin_set", at=T1, role="admin"))

    member = await _member(db)
    assert member.role == "admin"
    assert member.is_active is True
    assert member.active_since == T0

    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("admin_unset", at=T2, role="member"))

    member = await _member(db)
    assert member.role == "member"
    assert member.is_active is True
    assert member.active_since == T0
    assert member.inactive_since is None


@pytest.mark.asyncio
async def test_leave_then_rejoin_clears_inactive_since(
    db: SqliteDatabaseHelper,
) -> None:
    """退群再回来: 活跃起点是这次加入的时间, 旧的离开时间必须清掉."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("approve", at=T0))
        await record_member_event(s, _member_event("leave", at=T1))

    member = await _member(db)
    assert member.is_active is False
    assert member.active_since == T0
    assert member.inactive_since == T1

    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("invite", at=T2))

    member = await _member(db)
    assert member.is_active is True
    assert member.active_since == T2
    assert member.inactive_since is None


@pytest.mark.asyncio
async def test_kick_marks_member_inactive(db: SqliteDatabaseHelper) -> None:
    """被踢出属于真的离开."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_member_event(s, _member_event("approve", at=T0))
        await record_member_event(s, _member_event("kick", at=T1))

    member = await _member(db)
    assert member.is_active is False
    assert member.inactive_since == T1
    assert member.active_since == T0
