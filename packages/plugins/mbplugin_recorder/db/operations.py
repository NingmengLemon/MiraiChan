from datetime import UTC, datetime
from typing import Any

from lemony_storage_helper.database.utils import auto_begin, queryable
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from .dto import (
    AccountInput,
    ConversationInput,
    IdentityInput,
    MediaSourceInput,
    MemberEventInput,
    NoticeInput,
    RecordedMessageInput,
)
from .enums import MediaDownloadStatus
from .models import (
    Account,
    Conversation,
    ConversationMember,
    ConversationMemberEvent,
    ExternalIdentity,
    MediaAttachment,
    MediaObject,
    MediaSource,
    Message,
    MessageSegment,
    Notice,
    RawEventLog,
    now_datetime,
)

__all__ = [
    "get_or_create_account",
    "get_or_create_identity",
    "get_or_create_conversation",
    "upsert_conversation_member",
    "record_member_event",
    "record_notice",
    "record_message",
    "list_pending_media_sources",
    "mark_media_source_downloading",
    "mark_media_source_failed",
    "mark_media_source_downloaded",
]


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _is_after(left: datetime, right: datetime) -> bool:
    return _as_aware(left) > _as_aware(right)


def _merge_attrs(obj: object, **attrs: object) -> bool:
    changed = False
    for key, value in attrs.items():
        if value is not None and getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True
    return changed


async def get_or_create_account(
    session: AsyncSession,
    payload: AccountInput,
) -> Account:
    stmt = select(Account).where(
        queryable(Account.protocol) == payload.protocol,
        queryable(Account.self_id) == payload.self_id,
    )
    account = (await session.execute(stmt)).scalar_one_or_none()
    now = now_datetime()
    if account is None:
        account = Account(
            protocol=payload.protocol,
            self_id=payload.self_id,
            display_name=payload.display_name,
            raw_profile=payload.raw_profile,
        )
        session.add(account)
        await session.flush()
        return account
    if _merge_attrs(
        account,
        display_name=payload.display_name,
        raw_profile=payload.raw_profile,
    ):
        account.updated_at = now
    return account


async def get_or_create_identity(
    session: AsyncSession,
    payload: IdentityInput,
) -> ExternalIdentity:
    account: Account | None = None
    if payload.account is not None:
        account = await get_or_create_account(session, payload.account)

    stmt = select(ExternalIdentity).where(
        queryable(ExternalIdentity.protocol) == payload.protocol,
        queryable(ExternalIdentity.namespace) == payload.namespace,
        queryable(ExternalIdentity.external_id) == payload.external_id,
    )
    identity = (await session.execute(stmt)).scalar_one_or_none()
    now = now_datetime()
    if identity is None:
        identity = ExternalIdentity(
            protocol=payload.protocol,
            namespace=payload.namespace,
            external_id=payload.external_id,
            display_name=payload.display_name,
            raw_profile=payload.raw_profile,
            last_seen_at=payload.seen_at,
            account_id=account.id if account is not None else None,
        )
        try:
            async with session.begin_nested():
                session.add(identity)
                await session.flush()
            return identity
        except IntegrityError:
            identity = (await session.execute(stmt)).scalar_one_or_none()
            if identity is None:
                raise

    changed = _merge_attrs(
        identity,
        display_name=payload.display_name,
        raw_profile=payload.raw_profile,
    )
    if account is not None and identity.account_id != account.id:
        identity.account_id = account.id
        changed = True
    if payload.seen_at is not None and (
        identity.last_seen_at is None
        or _is_after(payload.seen_at, identity.last_seen_at)
    ):
        identity.last_seen_at = payload.seen_at
        changed = True
    if changed:
        identity.updated_at = now
    return identity


async def get_or_create_conversation(
    session: AsyncSession,
    *,
    account: Account,
    payload: ConversationInput,
) -> Conversation:
    stmt = select(Conversation).where(
        queryable(Conversation.account_id) == account.id,
        queryable(Conversation.type) == payload.type,
        queryable(Conversation.external_id) == payload.external_id,
    )
    conversation = (await session.execute(stmt)).scalar_one_or_none()
    now = now_datetime()
    if conversation is None:
        conversation = Conversation(
            account_id=account.id,
            type=payload.type,
            external_id=payload.external_id,
            external_key=payload.external_key,
            title=payload.title,
            raw_profile=payload.raw_profile,
            last_message_at=payload.last_message_at,
        )
        try:
            async with session.begin_nested():
                session.add(conversation)
                await session.flush()
            return conversation
        except IntegrityError:
            conversation = (await session.execute(stmt)).scalar_one_or_none()
            if conversation is None:
                raise

    changed = _merge_attrs(
        conversation,
        external_key=payload.external_key,
        title=payload.title,
        raw_profile=payload.raw_profile,
    )
    if payload.last_message_at is not None and (
        conversation.last_message_at is None
        or _is_after(payload.last_message_at, conversation.last_message_at)
    ):
        conversation.last_message_at = payload.last_message_at
        changed = True
    if changed:
        conversation.updated_at = now
    return conversation


async def upsert_conversation_member(
    session: AsyncSession,
    *,
    conversation: Conversation,
    identity: ExternalIdentity,
    nickname: str | None = None,
    role: str | None = None,
    is_active: bool = True,
    active_since: datetime | None = None,
    inactive_since: datetime | None = None,
) -> ConversationMember:
    stmt = select(ConversationMember).where(
        queryable(ConversationMember.conversation_id) == conversation.id,
        queryable(ConversationMember.identity_id) == identity.id,
    )
    member = (await session.execute(stmt)).scalar_one_or_none()
    now = now_datetime()
    if member is None:
        member = ConversationMember(
            conversation_id=conversation.id,
            identity_id=identity.id,
            nickname=nickname,
            role=role,
            is_active=is_active,
            active_since=active_since,
            inactive_since=inactive_since,
        )
        session.add(member)
        await session.flush()
        return member

    changed = _merge_attrs(member, nickname=nickname, role=role)
    if member.is_active != is_active:
        member.is_active = is_active
        changed = True
    if active_since is not None and member.active_since != active_since:
        member.active_since = active_since
        changed = True
    if inactive_since is not None and member.inactive_since != inactive_since:
        member.inactive_since = inactive_since
        changed = True
    if changed:
        member.updated_at = now
    return member


async def _record_raw_event(
    session: AsyncSession,
    *,
    account: Account | None,
    protocol: str,
    self_id: str,
    post_type: str,
    event_type: str | None,
    occurred_at: datetime,
    raw_event: dict[str, Any] | None,
    external_event_id: str | None = None,
) -> RawEventLog | None:
    if raw_event is None:
        return None
    log = RawEventLog(
        protocol=protocol,
        self_id=self_id,
        post_type=post_type,
        event_type=event_type,
        external_event_id=external_event_id,
        occurred_at=occurred_at,
        raw_event=raw_event,
        account_id=account.id if account is not None else None,
    )
    session.add(log)
    await session.flush()
    return log


async def record_member_event(
    session: AsyncSession,
    payload: MemberEventInput,
) -> ConversationMemberEvent:
    async with auto_begin(session):
        account = await get_or_create_account(session, payload.account)
        conversation = await get_or_create_conversation(
            session,
            account=account,
            payload=payload.conversation,
        )
        identity = await get_or_create_identity(session, payload.identity)
        operator = (
            await get_or_create_identity(session, payload.operator)
            if payload.operator is not None
            else None
        )
        raw_event = await _record_raw_event(
            session,
            account=account,
            protocol=payload.account.protocol,
            self_id=payload.account.self_id,
            post_type="notice",
            event_type=payload.event_type,
            occurred_at=payload.happened_at,
            raw_event=payload.raw_event,
            external_event_id=payload.raw_event_id,
        )

        event_type = payload.event_type.lower()
        is_active = event_type in {
            "join",
            "invite",
            "approve",
            "increase",
            "admin_set",
            "lift_ban",
        }
        await upsert_conversation_member(
            session,
            conversation=conversation,
            identity=identity,
            nickname=payload.nickname,
            role=payload.role,
            is_active=is_active,
            active_since=payload.happened_at if is_active else None,
            inactive_since=None if is_active else payload.happened_at,
        )
        event = ConversationMemberEvent(
            conversation_id=conversation.id,
            identity_id=identity.id,
            operator_identity_id=operator.id if operator is not None else None,
            raw_event_id=raw_event.id if raw_event is not None else None,
            event_type=payload.event_type,
            happened_at=payload.happened_at,
            nickname=payload.nickname,
            role=payload.role,
            reason=payload.reason,
            raw_event=payload.raw_event,
        )
        session.add(event)
        await session.flush()
        return event


async def record_notice(
    session: AsyncSession,
    payload: NoticeInput,
) -> Notice:
    async with auto_begin(session):
        account = await get_or_create_account(session, payload.account)
        conversation = (
            await get_or_create_conversation(
                session,
                account=account,
                payload=payload.conversation,
            )
            if payload.conversation is not None
            else None
        )
        actor = (
            await get_or_create_identity(session, payload.actor)
            if payload.actor is not None
            else None
        )
        target = (
            await get_or_create_identity(session, payload.target)
            if payload.target is not None
            else None
        )
        operator = (
            await get_or_create_identity(session, payload.operator)
            if payload.operator is not None
            else None
        )
        media_source = (
            await _upsert_media_source(
                session, account=account, payload=payload.media_source
            )
            if payload.media_source is not None
            else None
        )
        raw_event = await _record_raw_event(
            session,
            account=account,
            protocol=payload.account.protocol,
            self_id=payload.account.self_id,
            post_type="notice",
            event_type=payload.notice_type,
            occurred_at=payload.happened_at,
            raw_event=payload.raw_event,
            external_event_id=payload.external_notice_id,
        )
        notice = Notice(
            account_id=account.id,
            conversation_id=conversation.id if conversation is not None else None,
            actor_identity_id=actor.id if actor is not None else None,
            target_identity_id=target.id if target is not None else None,
            operator_identity_id=operator.id if operator is not None else None,
            raw_event_id=raw_event.id if raw_event is not None else None,
            media_source_id=media_source.id if media_source is not None else None,
            notice_type=payload.notice_type,
            sub_type=payload.sub_type,
            external_notice_id=payload.external_notice_id,
            external_message_id=payload.external_message_id,
            happened_at=payload.happened_at,
            summary=payload.summary,
            detail=payload.detail,
        )
        session.add(notice)
        if payload.notice_type in {"group_recall", "friend_recall"}:
            await _mark_recalled_message(
                session,
                account=account,
                conversation=conversation,
                external_message_id=payload.external_message_id,
                happened_at=payload.happened_at,
            )
        await session.flush()
        return notice


async def _mark_recalled_message(
    session: AsyncSession,
    *,
    account: Account,
    conversation: Conversation | None,
    external_message_id: str | None,
    happened_at: datetime,
) -> None:
    if external_message_id is None:
        return
    conditions = [
        queryable(Message.account_id) == account.id,
        queryable(Message.external_message_id) == external_message_id,
    ]
    if conversation is not None:
        conditions.append(queryable(Message.conversation_id) == conversation.id)
    stmt = select(Message).where(*conditions)
    message = (await session.execute(stmt)).scalar_one_or_none()
    if message is not None:
        message.deleted_at = happened_at


async def _upsert_media_object(
    session: AsyncSession,
    payload: MediaSourceInput,
) -> MediaObject | None:
    if not any(
        value is not None
        for value in (
            payload.sha256,
            payload.md5,
            payload.size,
            payload.mime_type,
            payload.cache_path,
        )
    ):
        return None
    if payload.sha256 is not None:
        stmt = select(MediaObject).where(
            queryable(MediaObject.sha256) == payload.sha256,
            queryable(MediaObject.size) == payload.size,
        )
        media_object = (await session.execute(stmt)).scalar_one_or_none()
        if media_object is not None:
            changed = _merge_attrs(
                media_object,
                md5=payload.md5,
                mime_type=payload.mime_type,
                cache_path=payload.cache_path,
            )
            if changed:
                media_object.updated_at = now_datetime()
            return media_object
    media_object = MediaObject(
        sha256=payload.sha256,
        md5=payload.md5,
        size=payload.size,
        mime_type=payload.mime_type,
        media_type=payload.media_type,
        cache_path=payload.cache_path,
    )
    session.add(media_object)
    await session.flush()
    return media_object


async def _upsert_media_source(
    session: AsyncSession,
    *,
    account: Account,
    payload: MediaSourceInput,
) -> MediaSource:
    media_object = await _upsert_media_object(session, payload)
    stmt = select(MediaSource).where(
        queryable(MediaSource.account_id) == account.id,
        queryable(MediaSource.source_file_id) == payload.source_file_id,
    )
    source = (await session.execute(stmt)).scalar_one_or_none()
    now = now_datetime()
    if source is None:
        source = MediaSource(
            account_id=account.id,
            media_object_id=media_object.id if media_object is not None else None,
            source_file_id=payload.source_file_id,
            media_type=payload.media_type,
            url=payload.url,
            download_status=payload.download_status,
            download_error=payload.download_error,
        )
        session.add(source)
        await session.flush()
        return source

    changed = _merge_attrs(
        source,
        url=payload.url,
        download_error=payload.download_error,
    )
    if media_object is not None and source.media_object_id != media_object.id:
        source.media_object_id = media_object.id
        changed = True
    if source.media_type != payload.media_type:
        source.media_type = payload.media_type
        changed = True
    if source.download_status != payload.download_status:
        source.download_status = payload.download_status
        changed = True
    if changed:
        source.updated_at = now
    return source


async def record_message(
    session: AsyncSession,
    payload: RecordedMessageInput,
) -> Message:
    async with auto_begin(session):
        account = await get_or_create_account(session, payload.account)
        conversation_payload = payload.conversation
        if conversation_payload.last_message_at is None:
            conversation_payload = ConversationInput(
                type=conversation_payload.type,
                external_id=conversation_payload.external_id,
                title=conversation_payload.title,
                external_key=conversation_payload.external_key,
                raw_profile=conversation_payload.raw_profile,
                last_message_at=payload.sent_at,
            )
        conversation = await get_or_create_conversation(
            session,
            account=account,
            payload=conversation_payload,
        )
        sender = await get_or_create_identity(
            session,
            IdentityInput(
                protocol=payload.sender.protocol,
                namespace=payload.sender.namespace,
                external_id=payload.sender.external_id,
                display_name=payload.sender.display_name,
                raw_profile=payload.sender.raw_profile,
                seen_at=payload.sent_at,
                account=payload.sender.account,
            ),
        )
        await upsert_conversation_member(
            session,
            conversation=conversation,
            identity=sender,
            nickname=payload.sender_conversation_name,
            is_active=True,
            active_since=payload.sent_at,
        )
        raw_event = await _record_raw_event(
            session,
            account=account,
            protocol=payload.account.protocol,
            self_id=payload.account.self_id,
            post_type="message",
            event_type=payload.raw_event_type,
            occurred_at=payload.sent_at,
            raw_event=payload.raw_event,
            external_event_id=payload.raw_event_id,
        )

        stmt = select(Message).where(
            queryable(Message.account_id) == account.id,
            queryable(Message.conversation_id) == conversation.id,
            queryable(Message.external_message_id) == payload.external_message_id,
        )
        message = (await session.execute(stmt)).scalar_one_or_none()
        if message is None:
            message = Message(
                account_id=account.id,
                conversation_id=conversation.id,
                sender_identity_id=sender.id,
                raw_event_id=raw_event.id if raw_event is not None else None,
                external_message_id=payload.external_message_id,
                external_message_key=payload.external_message_key,
                sent_at=payload.sent_at,
                received_at=payload.received_at or now_datetime(),
                edited_at=payload.edited_at,
                deleted_at=payload.deleted_at,
                text_content=payload.text_content,
                index_text=payload.index_text,
                reply_to_external_message_id=payload.reply_to_external_message_id,
                sender_display_name=payload.sender.display_name,
                sender_conversation_name=payload.sender_conversation_name,
            )
            session.add(message)
            await session.flush()
        else:
            _merge_attrs(
                message,
                external_message_key=payload.external_message_key,
                text_content=payload.text_content,
                index_text=payload.index_text,
                reply_to_external_message_id=payload.reply_to_external_message_id,
                sender_display_name=payload.sender.display_name,
                sender_conversation_name=payload.sender_conversation_name,
            )
            if raw_event is not None:
                message.raw_event_id = raw_event.id
            if payload.edited_at is not None:
                message.edited_at = payload.edited_at
            if payload.deleted_at is not None:
                message.deleted_at = payload.deleted_at
            return message

        for order, segment_input in enumerate(payload.segments):
            segment = MessageSegment(
                message_id=message.id,
                order=order,
                type=segment_input.type,
                data=segment_input.data,
                text=segment_input.text,
            )
            session.add(segment)
            await session.flush()
            for media_input in segment_input.media_sources:
                source = await _upsert_media_source(
                    session,
                    account=account,
                    payload=media_input,
                )
                attachment = MediaAttachment(
                    message_id=message.id,
                    segment_id=segment.id,
                    media_source_id=source.id,
                    media_object_id=source.media_object_id,
                    media_type=media_input.media_type,
                )
                session.add(attachment)
        await session.flush()
        return message


async def list_pending_media_sources(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> list[MediaSource]:
    stmt = (
        select(MediaSource)
        .where(
            queryable(MediaSource.download_status).in_(
                [MediaDownloadStatus.PENDING, MediaDownloadStatus.FAILED]
            ),
            queryable(MediaSource.url).is_not(None),
        )
        .order_by(col(MediaSource.created_at))
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def mark_media_source_downloading(
    session: AsyncSession,
    source_id: Any,
) -> None:
    async with auto_begin(session):
        source = await session.get(MediaSource, source_id)
        if source is None:
            return
        source.download_status = MediaDownloadStatus.DOWNLOADING
        source.download_error = None
        source.updated_at = now_datetime()


async def mark_media_source_failed(
    session: AsyncSession,
    source_id: Any,
    error: str,
) -> None:
    async with auto_begin(session):
        source = await session.get(MediaSource, source_id)
        if source is None:
            return
        source.download_status = MediaDownloadStatus.FAILED
        source.download_error = error[:1000]
        source.updated_at = now_datetime()


async def mark_media_source_downloaded(
    session: AsyncSession,
    source_id: Any,
    payload: MediaSourceInput,
) -> None:
    async with auto_begin(session):
        source = await session.get(MediaSource, source_id)
        if source is None:
            return
        media_object = await _upsert_media_object(session, payload)
        source.media_object_id = media_object.id if media_object is not None else None
        source.url = payload.url or source.url
        source.download_status = MediaDownloadStatus.DOWNLOADED
        source.download_error = None
        source.updated_at = now_datetime()
