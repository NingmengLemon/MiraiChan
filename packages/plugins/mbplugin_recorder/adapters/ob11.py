from datetime import datetime
from typing import Literal

from lemony_utils.time import tzaware_datetime_from_timestamp
from melobot.protocols.onebot.v11.adapter.event import (
    FriendAddNoticeEvent,
    FriendRecallNoticeEvent,
    GroupAdminNoticeEvent,
    GroupBanNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    GroupRecallNoticeEvent,
    GroupUploadNoticeEvent,
    HonorNotifyEvent,
    LuckyKingNotifyEvent,
    MessageEvent,
    NoticeEvent,
    NotifyNoticeEvent,
    PokeNotifyEvent,
)
from melobot.protocols.onebot.v11.adapter.segment import Segment

from ..db.enums import MediaDownloadStatus
from ..db.dto import (
    AccountInput,
    ConversationInput,
    IdentityInput,
    MediaSourceInput,
    MemberEventInput,
    MessageSegmentInput,
    NoticeInput,
    RecordedMessageInput,
)


class OneBot11MessageRecorderAdapter:
    def supports(self, event: object) -> bool:
        return isinstance(event, MessageEvent)

    def supports_notice(self, event: object) -> bool:
        return isinstance(event, NoticeEvent)

    def to_recorded_message(self, event: MessageEvent) -> RecordedMessageInput:
        occurred_at = tzaware_datetime_from_timestamp(event.time)
        conversation_type, conversation_id = _conversation_identity(event)
        sender_card_name = _sender_card_name(event)
        sender_display_name = event.sender.nickname
        account = _account_input(event)
        conversation = ConversationInput(
            type=conversation_type,
            external_id=conversation_id,
            title=None,
            external_key=_conversation_key(event),
            raw_profile={"raw": event.raw},
            last_message_at=occurred_at,
        )
        sender = IdentityInput(
            protocol=str(event.protocol),
            namespace="user",
            external_id=str(event.user_id),
            display_name=sender_display_name,
            raw_profile={"sender": dict(event.raw.get("sender", {}))},
            seen_at=occurred_at,
            account=account,
        )
        return RecordedMessageInput(
            account=account,
            conversation=conversation,
            sender=sender,
            external_message_id=str(event.message_id),
            sent_at=occurred_at,
            external_message_key=_message_key(event),
            sender_conversation_name=sender_card_name,
            text_content=event.text or None,
            index_text=event.text or None,
            reply_to_external_message_id=_reply_to_external_message_id(event),
            raw_event=event.raw,
            raw_event_type=event.post_type,
            raw_event_id=str(event.message_id),
            segments=[_segment_to_input(event, segment) for segment in event.message],
        )

    def to_member_event(self, event: NoticeEvent) -> MemberEventInput | None:
        if not self.supports_notice(event):
            return None
        group_id = getattr(event, "group_id", None)
        user_id = getattr(event, "user_id", None)
        if group_id is None or user_id is None:
            return None
        occurred_at = tzaware_datetime_from_timestamp(event.time)
        account = _account_input(event)
        conversation = ConversationInput(
            type="group",
            external_id=str(group_id),
            external_key={"type": "group", "group_id": group_id},
            raw_profile={"raw": event.raw},
        )
        identity = IdentityInput(
            protocol=str(event.protocol),
            namespace="user",
            external_id=str(user_id),
            seen_at=occurred_at,
            account=account,
        )
        operator_id = getattr(event, "operator_id", None)
        operator = (
            IdentityInput(
                protocol=str(event.protocol),
                namespace="user",
                external_id=str(operator_id),
                seen_at=occurred_at,
                account=account,
            )
            if operator_id is not None
            else None
        )
        return MemberEventInput(
            account=account,
            conversation=conversation,
            identity=identity,
            operator=operator,
            event_type=_notice_event_type(event),
            happened_at=occurred_at,
            role=_notice_role(event),
            reason=_notice_reason(event),
            raw_event=event.raw,
            raw_event_id=_notice_raw_event_id(event),
        )

    def to_notice(self, event: NoticeEvent) -> NoticeInput | None:
        if not self.supports_notice(event):
            return None
        occurred_at = tzaware_datetime_from_timestamp(event.time)
        account = _account_input(event)
        conversation = _notice_conversation(event)
        actor = _notice_actor(event, account, occurred_at)
        target = _notice_target(event, account, occurred_at)
        operator = _notice_operator(event, account, occurred_at)
        media_source = _notice_media_source(event)
        sub_type = getattr(event, "sub_type", None)
        return NoticeInput(
            account=account,
            conversation=conversation,
            actor=actor,
            target=target,
            operator=operator,
            media_source=media_source,
            notice_type=event.notice_type,
            sub_type=str(sub_type) if sub_type is not None else None,
            happened_at=occurred_at,
            external_notice_id=_notice_raw_event_id(event),
            external_message_id=_notice_external_message_id(event),
            summary=_notice_summary(event),
            detail=_notice_detail(event),
            raw_event=event.raw,
        )


def _account_input(event: MessageEvent | NoticeEvent) -> AccountInput:
    return AccountInput(
        protocol=str(event.protocol),
        self_id=str(event.self_id),
        display_name=None,
        raw_profile={"protocol": str(event.protocol), "self_id": str(event.self_id)},
    )


def _conversation_identity(
    event: MessageEvent,
) -> tuple[Literal["group", "private", "private_temp"], str]:
    if isinstance(event, GroupMessageEvent):
        return "group", str(event.group_id)
    if event.is_group_temp():
        temp_source = event.raw.get("temp_source")
        return "private_temp", str(temp_source or event.user_id)
    return "private", str(event.user_id)


def _conversation_key(event: MessageEvent) -> dict[str, object]:
    conversation_type, conversation_id = _conversation_identity(event)
    data: dict[str, object] = {
        "type": conversation_type,
        "id": conversation_id,
        "message_type": event.message_type,
        "sub_type": event.sub_type,
    }
    if isinstance(event, GroupMessageEvent):
        data["group_id"] = event.group_id
    if event.is_group_temp():
        data["temp_source"] = event.raw.get("temp_source")
    return data


def _message_key(event: MessageEvent) -> dict[str, object]:
    return {
        "message_id": event.message_id,
        "protocol": str(event.protocol),
        "self_id": str(event.self_id),
    }


def _sender_card_name(event: MessageEvent) -> str | None:
    if not isinstance(event, GroupMessageEvent):
        return None
    return event.sender.card or event.sender.nickname


def _reply_to_external_message_id(event: MessageEvent) -> str | None:
    for segment in event.message:
        if segment.type == "reply":
            reply_id = segment.data.get("id")
            return str(reply_id) if reply_id is not None else None
    return None


def _segment_to_input(
    event: MessageEvent,
    segment: Segment,
) -> MessageSegmentInput:
    return MessageSegmentInput(
        type=segment.type,
        data=segment.to_dict()["data"],
        text=_segment_text(segment),
        media_sources=_segment_media(event, segment),
    )


def _segment_text(segment: Segment) -> str | None:
    if segment.type == "text":
        text = segment.data.get("text")
        return str(text) if text is not None else None
    return None


def _segment_media(
    event: MessageEvent, segment: Segment
) -> tuple[MediaSourceInput, ...]:
    if segment.type not in {"image", "record", "video"}:
        return ()
    file_id = segment.data.get("file")
    if file_id is None:
        return ()
    url = segment.data.get("url")
    return (
        MediaSourceInput(
            source_file_id=str(file_id),
            media_type=_media_type(segment.type),
            url=str(url) if url is not None else None,
        ),
    )


def _media_type(segment_type: str) -> str:
    if segment_type == "record":
        return "voice"
    return segment_type


def _notice_conversation(event: NoticeEvent) -> ConversationInput | None:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return None
    return ConversationInput(
        type="group",
        external_id=str(group_id),
        external_key={"type": "group", "group_id": group_id},
        raw_profile={"raw": event.raw},
    )


def _identity_input(
    event: NoticeEvent,
    account: AccountInput,
    user_id: object | None,
    seen_at: datetime,
) -> IdentityInput | None:
    if user_id is None:
        return None
    return IdentityInput(
        protocol=str(event.protocol),
        namespace="user",
        external_id=str(user_id),
        seen_at=seen_at,
        account=account,
    )


def _notice_actor(
    event: NoticeEvent,
    account: AccountInput,
    seen_at: datetime,
) -> IdentityInput | None:
    return _identity_input(event, account, getattr(event, "user_id", None), seen_at)


def _notice_target(
    event: NoticeEvent,
    account: AccountInput,
    seen_at: datetime,
) -> IdentityInput | None:
    target_id = getattr(event, "target_id", None)
    if target_id is None:
        return None
    return _identity_input(event, account, target_id, seen_at)


def _notice_operator(
    event: NoticeEvent,
    account: AccountInput,
    seen_at: datetime,
) -> IdentityInput | None:
    operator_id = getattr(event, "operator_id", None)
    if operator_id is None:
        return None
    return _identity_input(event, account, operator_id, seen_at)


def _notice_media_source(event: NoticeEvent) -> MediaSourceInput | None:
    if not isinstance(event, GroupUploadNoticeEvent):
        return None
    return MediaSourceInput(
        source_file_id=event.file.id,
        media_type="file",
        size=event.file.size,
        download_status=MediaDownloadStatus.PENDING,
    )


def _notice_external_message_id(event: NoticeEvent) -> str | None:
    message_id = getattr(event, "message_id", None)
    if message_id is None:
        message_id = event.raw.get("message_id")
    return str(message_id) if message_id is not None else None


def _notice_detail(event: NoticeEvent) -> dict[str, object]:
    detail: dict[str, object] = {"raw": event.raw}
    if isinstance(event, GroupUploadNoticeEvent):
        detail["file"] = {
            "id": event.file.id,
            "name": event.file.name,
            "size": event.file.size,
            "busid": event.file.busid,
        }
    if isinstance(event, GroupBanNoticeEvent):
        detail["duration"] = event.duration
    if isinstance(event, HonorNotifyEvent):
        detail["honor_type"] = event.honor_type
    return detail


def _notice_summary(event: NoticeEvent) -> str:
    if event.notice_type == "group_msg_emoji_like":
        message_id = getattr(event, "message_id", None) or event.raw.get("message_id")
        is_add = event.raw.get("is_add")
        return f"group_msg_emoji_like:{message_id}:{'add' if is_add else 'remove'}"
    if isinstance(event, GroupUploadNoticeEvent):
        return f"group_upload:{event.file.name}"
    if isinstance(event, GroupRecallNoticeEvent):
        return f"group_recall:{event.message_id}"
    if isinstance(event, FriendRecallNoticeEvent):
        return f"friend_recall:{event.message_id}"
    if isinstance(event, FriendAddNoticeEvent):
        return f"friend_add:{event.user_id}"
    if isinstance(event, PokeNotifyEvent):
        return f"poke:{event.user_id}->{event.target_id}"
    if isinstance(event, LuckyKingNotifyEvent):
        return f"lucky_king:{event.user_id}->{event.target_id}"
    if isinstance(event, HonorNotifyEvent):
        return f"honor:{event.honor_type}:{event.user_id}"
    if isinstance(event, NotifyNoticeEvent):
        return f"notify:{event.sub_type}"
    sub_type = getattr(event, "sub_type", None)
    return (
        f"{event.notice_type}:{sub_type}" if sub_type is not None else event.notice_type
    )


def _notice_event_type(event: NoticeEvent) -> str:
    if isinstance(event, GroupIncreaseNoticeEvent):
        return event.sub_type
    if isinstance(event, GroupDecreaseNoticeEvent):
        return event.sub_type
    if isinstance(event, GroupBanNoticeEvent):
        return event.sub_type
    if isinstance(event, GroupAdminNoticeEvent):
        return f"admin_{event.sub_type}"
    return event.notice_type


def _notice_role(event: NoticeEvent) -> str | None:
    if isinstance(event, GroupAdminNoticeEvent):
        return "admin" if event.sub_type == "set" else "member"
    return None


def _notice_reason(event: NoticeEvent) -> str | None:
    if isinstance(event, GroupBanNoticeEvent):
        return f"duration={event.duration}"
    return getattr(event, "sub_type", None)


def _notice_raw_event_id(event: NoticeEvent) -> str:
    parts = [
        str(event.time),
        str(event.self_id),
        event.notice_type,
        str(getattr(event, "group_id", "")),
        str(getattr(event, "user_id", "")),
        str(getattr(event, "operator_id", "")),
        str(getattr(event, "sub_type", "")),
    ]
    return ":".join(parts)
