"""只读查询层: 在 recorder 的库上按会话检索消息与发言统计

这里只发 SELECT, 不写任何东西; 会话按 (协议, 机器人自身账号, 群号) 定位, 不依赖群名。
SQLModel 的字段注解是普通 python 类型, 所以列上的比较与 LIKE 都要经过 ``col()`` 包一层。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from mbplugin_recorder.db.models import Account, Conversation, ExternalIdentity, Message
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

__all__ = [
    "GroupRef",
    "Hit",
    "SpeakerStat",
    "find_conversation_id",
    "search_messages",
    "speaker_stats",
]

#: 发送者显示名: 优先群名片, 其次昵称
_SENDER = func.coalesce(
    col(Message.sender_conversation_name), col(Message.sender_display_name), "未知"
)


@dataclass(frozen=True, slots=True)
class GroupRef:
    protocol: str
    self_id: str
    group_id: str


@dataclass(frozen=True, slots=True)
class Hit:
    sent_at: datetime
    sender: str
    text: str


@dataclass(frozen=True, slots=True)
class SpeakerStat:
    sender: str
    count: int


async def find_conversation_id(session: AsyncSession, ref: GroupRef) -> UUID | None:
    stmt = (
        select(col(Conversation.id))
        .join(Account, col(Conversation.account_id) == col(Account.id))
        .where(
            col(Account.protocol) == ref.protocol,
            col(Account.self_id) == ref.self_id,
            col(Conversation.type) == "group",
            col(Conversation.external_id) == ref.group_id,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


def _filters(
    conversation_id: UUID,
    *,
    since: datetime,
    until: datetime | None,
    exclude_sender_external_ids: tuple[str, ...],
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = [
        col(Message.conversation_id) == conversation_id,
        col(Message.deleted_at).is_(None),
        col(Message.text_content).is_not(None),
        col(Message.text_content) != "",
        col(Message.sent_at) >= since,
    ]
    if until is not None:
        filters.append(col(Message.sent_at) <= until)
    if exclude_sender_external_ids:
        filters.append(
            or_(
                col(ExternalIdentity.external_id).is_(None),
                col(ExternalIdentity.external_id).not_in(exclude_sender_external_ids),
            )
        )
    return filters


async def search_messages(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    since: datetime,
    until: datetime | None = None,
    keywords: tuple[str, ...] = (),
    speaker: str | None = None,
    exclude_sender_external_ids: tuple[str, ...] = (),
    limit: int = 20,
) -> list[Hit]:
    stmt = (
        select(_SENDER, col(Message.sent_at), col(Message.text_content))
        .join(
            ExternalIdentity,
            col(Message.sender_identity_id) == col(ExternalIdentity.id),
            isouter=True,
        )
        .where(
            *_filters(
                conversation_id,
                since=since,
                until=until,
                exclude_sender_external_ids=exclude_sender_external_ids,
            )
        )
    )
    for keyword in keywords:
        if keyword:
            stmt = stmt.where(col(Message.text_content).contains(keyword))
    if speaker:
        stmt = stmt.where(_SENDER.contains(speaker))
    stmt = stmt.order_by(col(Message.sent_at).desc()).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [
        Hit(sent_at=sent_at, sender=sender or "未知", text=text or "")
        for sender, sent_at, text in rows
    ]


async def speaker_stats(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    since: datetime,
    until: datetime | None = None,
    exclude_sender_external_ids: tuple[str, ...] = (),
    limit: int = 10,
) -> list[SpeakerStat]:
    total: Any = func.count().label("n")
    stmt = (
        select(_SENDER, total)
        .join(
            ExternalIdentity,
            col(Message.sender_identity_id) == col(ExternalIdentity.id),
            isouter=True,
        )
        .where(
            *_filters(
                conversation_id,
                since=since,
                until=until,
                exclude_sender_external_ids=exclude_sender_external_ids,
            )
        )
        .group_by(_SENDER)
        .order_by(total.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [SpeakerStat(sender=sender or "未知", count=count) for sender, count in rows]
