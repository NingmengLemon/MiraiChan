from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from lemony_storage_helper.database.utils import queryable
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import col

from .db.enums import MediaDownloadStatus
from .db.models import (
    Account,
    Conversation,
    ExternalIdentity,
    MediaAttachment,
    MediaObject,
    MediaSource,
    Message,
    MessageSegment,
)
from .db.views import MessageView, MessageWindowQuery, SegmentView


@dataclass(slots=True)
class MessageContextQuery:
    account_protocol: str
    account_self_id: str
    conversation_type: str
    conversation_external_id: str
    base_external_message_id: str
    sender_external_id: str | None = None
    earlier: int = 0
    later: int = 0
    sender_only: bool = False


class RecorderService:
    def __init__(self, db: SqliteDatabaseHelper) -> None:
        self.db = db

    def get_session(self) -> AsyncSession:
        return self.db.get_session(style="sqlalchemy")

    async def get_context_messages(self, query: MessageContextQuery) -> list[Message]:
        async with self.get_session() as session:
            conversation = await self._get_conversation(
                session,
                protocol=query.account_protocol,
                self_id=query.account_self_id,
                conversation_type=query.conversation_type,
                external_id=query.conversation_external_id,
            )
            if conversation is None:
                return []
            base_message = await self._get_base_message(
                session,
                conversation_id=conversation.id,
                external_message_id=query.base_external_message_id,
                sender_external_id=query.sender_external_id,
            )
            if base_message is None:
                return []
            if query.earlier == 0 and query.later == 0:
                return [base_message]

            sender_filter = []
            if query.sender_only:
                sender_filter.append(
                    col(Message.sender_identity_id) == base_message.sender_identity_id
                )

            earlier_messages: list[Message] = []
            if query.earlier > 0:
                earlier_stmt = (
                    select(Message)
                    .options(
                        selectinload(queryable(Message.sender)),
                        selectinload(queryable(Message.conversation)),
                    )
                    .where(
                        queryable(Message.conversation_id) == conversation.id,
                        or_(
                            queryable(Message.sent_at) < base_message.sent_at,
                            and_(
                                queryable(Message.sent_at) == base_message.sent_at,
                                queryable(Message.id) < base_message.id,
                            ),
                        ),
                        *sender_filter,
                    )
                    .order_by(col(Message.sent_at).desc(), col(Message.id).desc())
                    .limit(query.earlier)
                )
                earlier_messages = list(
                    (await session.execute(earlier_stmt)).scalars().all()
                )

            later_messages: list[Message] = []
            if query.later > 0:
                later_stmt = (
                    select(Message)
                    .options(
                        selectinload(queryable(Message.sender)),
                        selectinload(queryable(Message.conversation)),
                    )
                    .where(
                        queryable(Message.conversation_id) == conversation.id,
                        or_(
                            queryable(Message.sent_at) > base_message.sent_at,
                            and_(
                                queryable(Message.sent_at) == base_message.sent_at,
                                queryable(Message.id) > base_message.id,
                            ),
                        ),
                        *sender_filter,
                    )
                    .order_by(col(Message.sent_at).asc(), col(Message.id).asc())
                    .limit(query.later)
                )
                later_messages = list(
                    (await session.execute(later_stmt)).scalars().all()
                )

            return earlier_messages[::-1] + [base_message] + later_messages

    async def get_message_window(
        self, query: MessageWindowQuery
    ) -> list[MessageView] | None:
        """取以基准消息为 0 的相对闭区间 [start, end] 内的消息, 按时间升序。

        基准消息不在记录里时返回 None (与 "区间内没有消息" 的空列表区分开)。
        """
        lo, hi = sorted((query.start, query.end))
        async with self.get_session() as session:
            conversation = await self._get_conversation(
                session,
                protocol=query.account_protocol,
                self_id=query.account_self_id,
                conversation_type=query.conversation_type,
                external_id=query.conversation_external_id,
            )
            if conversation is None:
                return None
            base = await self._get_base_message(
                session,
                conversation_id=conversation.id,
                external_message_id=query.base_external_message_id,
                sender_external_id=None,
            )
            if base is None:
                return None
            excluded = tuple(query.exclude_sender_external_ids)
            if base.sender.external_id in excluded:
                return []

            filters = [queryable(Message.conversation_id) == conversation.id]
            if excluded:
                filters.append(
                    queryable(Message.sender_identity_id).not_in(
                        select(queryable(ExternalIdentity.id)).where(
                            queryable(ExternalIdentity.external_id).in_(excluded)
                        )
                    )
                )
            if query.sender_only:
                filters.append(
                    queryable(Message.sender_identity_id) == base.sender_identity_id
                )

            earlier: list[Message] = []
            if lo < 0:
                stmt = (
                    select(Message)
                    .options(selectinload(queryable(Message.sender)))
                    .where(
                        *filters,
                        or_(
                            queryable(Message.sent_at) < base.sent_at,
                            and_(
                                queryable(Message.sent_at) == base.sent_at,
                                queryable(Message.id) < base.id,
                            ),
                        ),
                    )
                    .order_by(col(Message.sent_at).desc(), col(Message.id).desc())
                    .limit(-lo)
                )
                earlier = list((await session.execute(stmt)).scalars().all())

            later: list[Message] = []
            if hi > 0:
                stmt = (
                    select(Message)
                    .options(selectinload(queryable(Message.sender)))
                    .where(
                        *filters,
                        or_(
                            queryable(Message.sent_at) > base.sent_at,
                            and_(
                                queryable(Message.sent_at) == base.sent_at,
                                queryable(Message.id) > base.id,
                            ),
                        ),
                    )
                    .order_by(col(Message.sent_at).asc(), col(Message.id).asc())
                    .limit(hi)
                )
                later = list((await session.execute(stmt)).scalars().all())

            # earlier 是按时间倒序取的, 第 i 个 (从 0 起) 的偏移是 -(i + 1)
            indexed: list[tuple[int, Message]] = [
                (-(i + 1), m) for i, m in enumerate(earlier)
            ]
            indexed.reverse()
            indexed.append((0, base))
            indexed.extend((i + 1, m) for i, m in enumerate(later))
            selected = [(off, m) for off, m in indexed if lo <= off <= hi]
            return await self._to_views(session, selected)

    async def _to_views(
        self, session: AsyncSession, selected: list[tuple[int, Message]]
    ) -> list[MessageView]:
        if not selected:
            return []
        message_ids = [m.id for _, m in selected]
        seg_rows = (
            (
                await session.execute(
                    select(MessageSegment)
                    .where(queryable(MessageSegment.message_id).in_(message_ids))
                    .order_by(col(MessageSegment.message_id), col(MessageSegment.order))
                )
            )
            .scalars()
            .all()
        )
        segment_ids = [s.id for s in seg_rows]
        media_rows = (
            await session.execute(
                select(
                    queryable(MediaAttachment.segment_id),
                    queryable(MediaObject.cache_path),
                )
                .join(
                    MediaSource,
                    queryable(MediaAttachment.media_source_id)
                    == queryable(MediaSource.id),
                )
                .join(
                    MediaObject,
                    queryable(MediaSource.media_object_id) == queryable(MediaObject.id),
                )
                .where(
                    queryable(MediaAttachment.segment_id).in_(segment_ids),
                    queryable(MediaSource.download_status)
                    == MediaDownloadStatus.DOWNLOADED,
                    queryable(MediaObject.cache_path).is_not(None),
                )
                .order_by(col(MediaAttachment.id))
            )
        ).all()
        paths: dict[UUID, list[str]] = defaultdict(list)
        for segment_id, cache_path in media_rows:
            # 查询条件已排除 NULL, 这里只是让类型收窄
            if segment_id is not None and cache_path is not None:
                paths[segment_id].append(cache_path)
        segments: dict[UUID, list[SegmentView]] = defaultdict(list)
        for s in seg_rows:
            segments[s.message_id].append(
                SegmentView(
                    order=s.order,
                    type=s.type,
                    data=MappingProxyType(dict(s.data)),
                    media_paths=tuple(paths.get(s.id, ())),
                )
            )
        return [
            MessageView(
                external_message_id=m.external_message_id,
                sender_external_id=m.sender.external_id,
                sender_display_name=m.sender_display_name,
                sender_conversation_name=m.sender_conversation_name,
                sent_at=m.sent_at,
                offset=offset,
                segments=tuple(segments.get(m.id, ())),
            )
            for offset, m in selected
        ]

    async def count_messages_by_sender(
        self,
        *,
        account_protocol: str,
        account_self_id: str,
        conversation_type: str,
        conversation_external_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, int]:
        async with self.get_session() as session:
            conversation = await self._get_conversation(
                session,
                protocol=account_protocol,
                self_id=account_self_id,
                conversation_type=conversation_type,
                external_id=conversation_external_id,
            )
            if conversation is None:
                return {}
            stmt = (
                select(
                    queryable(ExternalIdentity.external_id),
                    func.count(queryable(Message.id)),
                )
                .join(
                    Message,
                    queryable(Message.sender_identity_id)
                    == queryable(ExternalIdentity.id),
                )
                .where(
                    queryable(Message.conversation_id) == conversation.id,
                    queryable(Message.sent_at) >= start_at,
                    queryable(Message.sent_at) < end_at,
                )
                .group_by(queryable(ExternalIdentity.external_id))
                .order_by(func.count(queryable(Message.id)).desc())
            )
            return {
                sender_id: count
                for sender_id, count in (await session.execute(stmt)).all()
            }

    async def find_media_by_sha256(self, sha256: str) -> list[MediaObject]:
        async with self.get_session() as session:
            stmt = select(MediaObject).where(queryable(MediaObject.sha256) == sha256)
            return list((await session.execute(stmt)).scalars().all())

    async def list_pending_media(self, limit: int = 20) -> list[MediaSource]:
        from .db.operations import list_pending_media_sources

        async with self.get_session() as session:
            return await list_pending_media_sources(session, limit=limit)

    async def _get_conversation(
        self,
        session: AsyncSession,
        *,
        protocol: str,
        self_id: str,
        conversation_type: str,
        external_id: str,
    ) -> Conversation | None:
        stmt = (
            select(Conversation)
            .join(Account, queryable(Conversation.account_id) == queryable(Account.id))
            .where(
                queryable(Conversation.type) == conversation_type,
                queryable(Conversation.external_id) == external_id,
                queryable(Account.protocol) == protocol,
                queryable(Account.self_id) == self_id,
            )
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _get_base_message(
        self,
        session: AsyncSession,
        *,
        conversation_id: UUID,
        external_message_id: str,
        sender_external_id: str | None,
    ) -> Message | None:
        stmt = (
            select(Message)
            .options(
                selectinload(queryable(Message.sender)),
                selectinload(queryable(Message.conversation)),
            )
            .where(
                queryable(Message.conversation_id) == conversation_id,
                queryable(Message.external_message_id) == external_message_id,
            )
        )
        if sender_external_id is not None:
            stmt = stmt.join(
                ExternalIdentity,
                queryable(Message.sender_identity_id) == queryable(ExternalIdentity.id),
            ).where(queryable(ExternalIdentity.external_id) == sender_external_id)
        return (await session.execute(stmt)).scalar_one_or_none()
