from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .enums import MediaDownloadStatus

__all__ = [
    "AccountInput",
    "ConversationInput",
    "IdentityInput",
    "MediaSourceInput",
    "MessageSegmentInput",
    "RecordedMessageInput",
    "MemberEventInput",
    "NoticeInput",
]


@dataclass(slots=True)
class AccountInput:
    protocol: str
    self_id: str
    display_name: str | None = None
    raw_profile: dict[str, Any] | None = None


@dataclass(slots=True)
class IdentityInput:
    protocol: str
    namespace: str
    external_id: str
    display_name: str | None = None
    raw_profile: dict[str, Any] | None = None
    seen_at: datetime | None = None
    account: AccountInput | None = None


@dataclass(slots=True)
class ConversationInput:
    type: str
    external_id: str
    title: str | None = None
    external_key: dict[str, Any] | None = None
    raw_profile: dict[str, Any] | None = None
    last_message_at: datetime | None = None


@dataclass(slots=True)
class MediaSourceInput:
    source_file_id: str
    media_type: str
    url: str | None = None
    download_status: MediaDownloadStatus = MediaDownloadStatus.PENDING
    download_error: str | None = None
    sha256: str | None = None
    md5: str | None = None
    size: int | None = None
    mime_type: str | None = None
    cache_path: str | None = None


@dataclass(slots=True)
class MessageSegmentInput:
    type: str
    data: dict[str, Any]
    text: str | None = None
    media_sources: Sequence[MediaSourceInput] = field(default_factory=tuple)


@dataclass(slots=True)
class RecordedMessageInput:
    account: AccountInput
    conversation: ConversationInput
    sender: IdentityInput
    external_message_id: str
    sent_at: datetime
    external_message_key: dict[str, Any] | None = None
    received_at: datetime | None = None
    edited_at: datetime | None = None
    deleted_at: datetime | None = None
    text_content: str | None = None
    index_text: str | None = None
    reply_to_external_message_id: str | None = None
    sender_conversation_name: str | None = None
    raw_event: dict[str, Any] | None = None
    raw_event_type: str | None = None
    raw_event_id: str | None = None
    segments: Sequence[MessageSegmentInput] = field(default_factory=tuple)


@dataclass(slots=True)
class MemberEventInput:
    account: AccountInput
    conversation: ConversationInput
    identity: IdentityInput
    event_type: str
    happened_at: datetime
    operator: IdentityInput | None = None
    nickname: str | None = None
    role: str | None = None
    reason: str | None = None
    raw_event: dict[str, Any] | None = None
    raw_event_id: str | None = None


@dataclass(slots=True)
class NoticeInput:
    account: AccountInput
    notice_type: str
    happened_at: datetime
    sub_type: str | None = None
    conversation: ConversationInput | None = None
    actor: IdentityInput | None = None
    target: IdentityInput | None = None
    operator: IdentityInput | None = None
    external_notice_id: str | None = None
    external_message_id: str | None = None
    media_source: MediaSourceInput | None = None
    summary: str | None = None
    detail: dict[str, Any] | None = None
    raw_event: dict[str, Any] | None = None
