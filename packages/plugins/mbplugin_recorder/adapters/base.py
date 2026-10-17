from typing import Protocol, runtime_checkable

from ..db.dto import MemberEventInput, NoticeInput, RecordedMessageInput


@runtime_checkable
class MessageRecorderAdapter[EventT](Protocol):
    def supports(self, event: object) -> bool: ...

    def to_recorded_message(self, event: EventT) -> RecordedMessageInput: ...


@runtime_checkable
class NoticeRecorderAdapter[EventT](Protocol):
    def supports_notice(self, event: object) -> bool: ...

    def to_member_event(self, event: EventT) -> MemberEventInput | None: ...

    def to_notice(self, event: EventT) -> NoticeInput | None: ...
