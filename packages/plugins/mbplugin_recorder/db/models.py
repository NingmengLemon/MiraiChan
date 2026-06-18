from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, Union
from uuid import UUID

from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from lemony_storage_helper.database.utils import (
    GenericAsyncAttrs,
    datetime_column_tzaware,
)
from sqlalchemy import Enum, Index, UniqueConstraint
from sqlmodel import JSON, Column, Field, Relationship
from uuid_utils.compat import uuid7

from .enums import MediaDownloadStatus

__all__ = [
    "Account",
    "ExternalIdentity",
    "Conversation",
    "ConversationMember",
    "ConversationMemberEvent",
    "RawEventLog",
    "Notice",
    "Message",
    "MessageSegment",
    "MediaObject",
    "MediaSource",
    "MediaAttachment",
    "recorder_metadata",
]

Base, recorder_registry, recorder_metadata = SqliteDatabaseHelper.new_base("Recorder")


def now_datetime() -> datetime:
    return datetime.now(UTC)


class _AccountAwaitableAttrs:
    conversations: Awaitable[list["Conversation"]]
    identities: Awaitable[list["ExternalIdentity"]]
    raw_events: Awaitable[list["RawEventLog"]]
    messages: Awaitable[list["Message"]]
    media_sources: Awaitable[list["MediaSource"]]


class Account(Base, GenericAsyncAttrs[_AccountAwaitableAttrs], table=True):
    __tablename__ = "recorder_account"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    protocol: str = Field(index=True, description="协议标识, 例如 onebot-v11")
    self_id: str = Field(index=True, description="机器人/登录账号在该协议下的外部 ID")
    display_name: str | None = Field(default=None, description="账号显示名快照")
    raw_profile: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )
    updated_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    conversations: list["Conversation"] = Relationship(back_populates="account")
    identities: list["ExternalIdentity"] = Relationship(back_populates="account")
    raw_events: list["RawEventLog"] = Relationship(back_populates="account")
    messages: list["Message"] = Relationship(back_populates="account")
    media_sources: list["MediaSource"] = Relationship(back_populates="account")

    __table_args__ = (
        UniqueConstraint("protocol", "self_id", name="uq_recorder_account_identity"),
    )


class _ExternalIdentityAwaitableAttrs:
    account: Awaitable[Account | None]
    memberships: Awaitable[list["ConversationMember"]]
    member_events: Awaitable[list["ConversationMemberEvent"]]
    operated_member_events: Awaitable[list["ConversationMemberEvent"]]
    sent_messages: Awaitable[list["Message"]]


class ExternalIdentity(
    Base, GenericAsyncAttrs[_ExternalIdentityAwaitableAttrs], table=True
):
    __tablename__ = "recorder_external_identity"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    protocol: str = Field(index=True, description="协议标识")
    namespace: str = Field(
        index=True, description="身份命名空间, 例如 user/channel/bot"
    )
    external_id: str = Field(index=True, description="协议侧身份 ID")
    display_name: str | None = Field(default=None, description="显示名快照")
    raw_profile: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime, index=True),
    )
    last_seen_at: datetime | None = Field(default=None, index=True)
    updated_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    account_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_account.id",
        index=True,
        description="该身份若是本 bot 账号, 则指向对应账号",
    )
    account: Account | None = Relationship(back_populates="identities")

    memberships: list["ConversationMember"] = Relationship(back_populates="identity")
    member_events: list["ConversationMemberEvent"] = Relationship(
        back_populates="identity",
        sa_relationship_kwargs={"foreign_keys": "ConversationMemberEvent.identity_id"},
    )
    operated_member_events: list["ConversationMemberEvent"] = Relationship(
        back_populates="operator",
        sa_relationship_kwargs={
            "foreign_keys": "ConversationMemberEvent.operator_identity_id"
        },
    )
    sent_messages: list["Message"] = Relationship(back_populates="sender")

    __table_args__ = (
        UniqueConstraint(
            "protocol",
            "namespace",
            "external_id",
            name="uq_recorder_external_identity",
        ),
    )


class _ConversationAwaitableAttrs:
    account: Awaitable[Account]
    members: Awaitable[list["ConversationMember"]]
    member_events: Awaitable[list["ConversationMemberEvent"]]
    messages: Awaitable[list["Message"]]


class Conversation(Base, GenericAsyncAttrs[_ConversationAwaitableAttrs], table=True):
    __tablename__ = "recorder_conversation"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    type: str = Field(index=True, description="会话类型, 例如 group/private/channel")
    external_id: str = Field(index=True, description="协议侧主会话 ID")
    external_key: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="协议侧复合会话键, 用于表达临时会话/thread 等",
    )
    title: str | None = Field(default=None, description="会话名称快照")
    raw_profile: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )
    updated_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )
    last_message_at: datetime | None = Field(default=None, index=True)

    account_id: UUID = Field(foreign_key="recorder_account.id", index=True)
    account: Account = Relationship(back_populates="conversations")

    members: list["ConversationMember"] = Relationship(
        back_populates="conversation", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    member_events: list["ConversationMemberEvent"] = Relationship(
        back_populates="conversation", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    messages: list["Message"] = Relationship(back_populates="conversation")

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "type",
            "external_id",
            name="uq_recorder_conversation_identity",
        ),
        Index("ix_recorder_conversation_latest", "account_id", "last_message_at"),
    )


class ConversationMember(Base, table=True):
    __tablename__ = "recorder_conversation_member"

    conversation_id: UUID = Field(
        foreign_key="recorder_conversation.id",
        primary_key=True,
        index=True,
    )
    identity_id: UUID = Field(
        foreign_key="recorder_external_identity.id",
        primary_key=True,
        index=True,
    )
    nickname: str | None = Field(default=None, description="会话内昵称/群名片")
    role: str | None = Field(default=None, index=True, description="会话内角色")
    is_active: bool = Field(default=True, index=True)
    active_since: datetime | None = Field(default=None, index=True)
    inactive_since: datetime | None = Field(default=None, index=True)
    updated_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    conversation: Conversation = Relationship(back_populates="members")
    identity: ExternalIdentity = Relationship(back_populates="memberships")

    __table_args__ = (
        Index("ix_recorder_member_active", "conversation_id", "is_active"),
    )


class ConversationMemberEvent(Base, table=True):
    __tablename__ = "recorder_conversation_member_event"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    event_type: str = Field(index=True, description="join/leave/kick/ban/role 等")
    happened_at: datetime = Field(sa_column=datetime_column_tzaware(index=True))
    nickname: str | None = Field(default=None)
    role: str | None = Field(default=None)
    reason: str | None = Field(default=None)
    raw_event: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    conversation_id: UUID = Field(
        foreign_key="recorder_conversation.id",
        index=True,
    )
    identity_id: UUID = Field(
        foreign_key="recorder_external_identity.id",
        index=True,
    )
    operator_identity_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_external_identity.id",
        index=True,
    )
    raw_event_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_raw_event_log.id",
        index=True,
    )

    conversation: Conversation = Relationship(back_populates="member_events")
    identity: ExternalIdentity = Relationship(
        back_populates="member_events",
        sa_relationship_kwargs={"foreign_keys": "ConversationMemberEvent.identity_id"},
    )
    operator: ExternalIdentity | None = Relationship(
        back_populates="operated_member_events",
        sa_relationship_kwargs={
            "foreign_keys": "ConversationMemberEvent.operator_identity_id"
        },
    )

    __table_args__ = (
        Index(
            "ix_recorder_member_event_timeline",
            "conversation_id",
            "identity_id",
            "happened_at",
        ),
    )


class _RawEventLogAwaitableAttrs:
    account: Awaitable[Account | None]
    notices: Awaitable[list["Notice"]]
    message: Awaitable["Message | None"]


class RawEventLog(Base, GenericAsyncAttrs[_RawEventLogAwaitableAttrs], table=True):
    __tablename__ = "recorder_raw_event_log"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    protocol: str = Field(index=True)
    self_id: str = Field(index=True)
    post_type: str = Field(index=True)
    event_type: str | None = Field(default=None, index=True)
    external_event_id: str | None = Field(default=None, index=True)
    occurred_at: datetime = Field(sa_column=datetime_column_tzaware(index=True))
    received_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime, index=True),
    )
    raw_event: dict[str, Any] = Field(sa_column=Column(JSON))

    account_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_account.id",
        index=True,
    )
    account: Account | None = Relationship(back_populates="raw_events")
    notices: list["Notice"] = Relationship(back_populates="raw_event")
    message: Union["Message", None] = Relationship(
        back_populates="raw_event"
    )  # 引号括起的 "xxx | None" 会影响 sa 解析, 于是用 union 了

    __table_args__ = (
        Index("ix_recorder_raw_event_timeline", "protocol", "self_id", "occurred_at"),
    )


class _NoticeAwaitableAttrs:
    account: Awaitable[Account]
    conversation: Awaitable[Conversation | None]
    actor: Awaitable[ExternalIdentity | None]
    target: Awaitable[ExternalIdentity | None]
    operator: Awaitable[ExternalIdentity | None]
    raw_event: Awaitable[RawEventLog | None]
    media_source: Awaitable["MediaSource | None"]


class Notice(Base, GenericAsyncAttrs[_NoticeAwaitableAttrs], table=True):
    __tablename__ = "recorder_notice"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    notice_type: str = Field(index=True)
    sub_type: str | None = Field(default=None, index=True)
    external_notice_id: str | None = Field(default=None, index=True)
    external_message_id: str | None = Field(default=None, index=True)
    happened_at: datetime = Field(sa_column=datetime_column_tzaware(index=True))
    summary: str | None = Field(default=None, index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    account_id: UUID = Field(foreign_key="recorder_account.id", index=True)
    conversation_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_conversation.id",
        index=True,
    )
    actor_identity_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_external_identity.id",
        index=True,
    )
    target_identity_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_external_identity.id",
        index=True,
    )
    operator_identity_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_external_identity.id",
        index=True,
    )
    raw_event_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_raw_event_log.id",
        index=True,
    )
    media_source_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_media_source.id",
        index=True,
    )

    account: Account = Relationship()
    conversation: Conversation | None = Relationship()
    actor: ExternalIdentity | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Notice.actor_identity_id"}
    )
    target: ExternalIdentity | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Notice.target_identity_id"}
    )
    operator: ExternalIdentity | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Notice.operator_identity_id"}
    )
    raw_event: RawEventLog | None = Relationship(back_populates="notices")
    media_source: Union["MediaSource", None] = Relationship()

    __table_args__ = (
        Index("ix_recorder_notice_timeline", "account_id", "happened_at"),
        Index("ix_recorder_notice_kind_time", "notice_type", "sub_type", "happened_at"),
    )


class _MessageAwaitableAttrs:
    account: Awaitable[Account]
    conversation: Awaitable[Conversation]
    sender: Awaitable[ExternalIdentity]
    raw_event: Awaitable[RawEventLog | None]
    segments: Awaitable[list["MessageSegment"]]
    media_attachments: Awaitable[list["MediaAttachment"]]


class Message(Base, GenericAsyncAttrs[_MessageAwaitableAttrs], table=True):
    __tablename__ = "recorder_message"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    external_message_id: str = Field(index=True, description="协议侧消息 ID")
    external_message_key: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    sent_at: datetime = Field(sa_column=datetime_column_tzaware(index=True))
    received_at: datetime = Field(
        sa_column=datetime_column_tzaware(default=now_datetime, index=True)
    )
    edited_at: datetime | None = Field(default=None, index=True)
    deleted_at: datetime | None = Field(default=None, index=True)
    text_content: str | None = Field(default=None, index=True)
    index_text: str | None = Field(default=None, description="面向检索的规范化文本")
    reply_to_external_message_id: str | None = Field(default=None, index=True)
    sender_display_name: str | None = Field(default=None)
    sender_conversation_name: str | None = Field(default=None)

    account_id: UUID = Field(foreign_key="recorder_account.id", index=True)
    conversation_id: UUID = Field(foreign_key="recorder_conversation.id", index=True)
    sender_identity_id: UUID = Field(
        foreign_key="recorder_external_identity.id",
        index=True,
    )
    raw_event_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_raw_event_log.id",
        index=True,
    )

    account: Account = Relationship(back_populates="messages")
    conversation: Conversation = Relationship(back_populates="messages")
    sender: ExternalIdentity = Relationship(back_populates="sent_messages")
    raw_event: RawEventLog | None = Relationship(back_populates="message")
    segments: list["MessageSegment"] = Relationship(
        back_populates="message", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    media_attachments: list["MediaAttachment"] = Relationship(
        back_populates="message", sa_relationship_kwargs={"cascade": "all, delete"}
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "conversation_id",
            "external_message_id",
            name="uq_recorder_message_identity",
        ),
        Index("ix_recorder_message_timeline", "conversation_id", "sent_at", "id"),
        Index("ix_recorder_message_sender_time", "sender_identity_id", "sent_at"),
    )


class _MessageSegmentAwaitableAttrs:
    message: Awaitable[Message]
    media_attachments: Awaitable[list["MediaAttachment"]]


class MessageSegment(
    Base, GenericAsyncAttrs[_MessageSegmentAwaitableAttrs], table=True
):
    __tablename__ = "recorder_message_segment"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    order: int = Field(ge=0)
    type: str = Field(index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON))
    text: str | None = Field(default=None, index=True)

    message_id: UUID = Field(foreign_key="recorder_message.id", index=True)
    message: Message = Relationship(back_populates="segments")
    media_attachments: list["MediaAttachment"] = Relationship(
        back_populates="segment", sa_relationship_kwargs={"cascade": "all, delete"}
    )

    __table_args__ = (
        UniqueConstraint(
            "message_id", "order", name="uq_recorder_message_segment_order"
        ),
        Index("ix_recorder_segment_message_type", "message_id", "type"),
    )


class _MediaObjectAwaitableAttrs:
    sources: Awaitable[list["MediaSource"]]
    attachments: Awaitable[list["MediaAttachment"]]


class MediaObject(Base, GenericAsyncAttrs[_MediaObjectAwaitableAttrs], table=True):
    __tablename__ = "recorder_media_object"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    sha256: str | None = Field(default=None, index=True)
    md5: str | None = Field(default=None, index=True)
    size: int | None = Field(default=None, index=True)
    mime_type: str | None = Field(default=None, index=True)
    media_type: str = Field(index=True, description="image/voice/video/file 等")
    cache_path: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )
    updated_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    sources: list["MediaSource"] = Relationship(back_populates="media_object")
    attachments: list["MediaAttachment"] = Relationship(back_populates="media_object")

    __table_args__ = (Index("ix_recorder_media_object_hash", "sha256", "size"),)


class _MediaSourceAwaitableAttrs:
    account: Awaitable[Account]
    media_object: Awaitable[MediaObject | None]
    attachments: Awaitable[list["MediaAttachment"]]


class MediaSource(Base, GenericAsyncAttrs[_MediaSourceAwaitableAttrs], table=True):
    __tablename__ = "recorder_media_source"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    source_file_id: str = Field(index=True, description="协议侧 file_id/url key")
    media_type: str = Field(index=True)
    url: str | None = Field(default=None)
    download_status: MediaDownloadStatus = Field(
        default=MediaDownloadStatus.PENDING,
        sa_column=Column(
            Enum(
                MediaDownloadStatus,
                values_callable=lambda enum_class: [item.value for item in enum_class],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            index=True,
        ),
    )
    download_error: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )
    updated_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    account_id: UUID = Field(foreign_key="recorder_account.id", index=True)
    media_object_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_media_object.id",
        index=True,
    )
    account: Account = Relationship(back_populates="media_sources")
    media_object: MediaObject | None = Relationship(back_populates="sources")
    attachments: list["MediaAttachment"] = Relationship(back_populates="media_source")

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "source_file_id",
            name="uq_recorder_media_source_identity",
        ),
    )


class MediaAttachment(Base, table=True):
    __tablename__ = "recorder_media_attachment"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    media_type: str = Field(index=True)
    created_at: datetime = Field(
        default_factory=now_datetime,
        sa_column=datetime_column_tzaware(default=now_datetime),
    )

    message_id: UUID = Field(foreign_key="recorder_message.id", index=True)
    segment_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_message_segment.id",
        index=True,
    )
    media_source_id: UUID = Field(foreign_key="recorder_media_source.id", index=True)
    media_object_id: UUID | None = Field(
        default=None,
        foreign_key="recorder_media_object.id",
        index=True,
    )

    message: Message = Relationship(back_populates="media_attachments")
    segment: MessageSegment | None = Relationship(back_populates="media_attachments")
    media_source: MediaSource = Relationship(back_populates="attachments")
    media_object: MediaObject | None = Relationship(back_populates="attachments")

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "segment_id",
            "media_source_id",
            name="uq_recorder_media_attachment",
        ),
    )
