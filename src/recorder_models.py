import time
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from collections.abc import Awaitable
import uuid

from sqlmodel import Relationship, SQLModel, Field, JSON, CheckConstraint
from sqlalchemy import Column
from sqlalchemy.ext.asyncio.session import AsyncAttrs as _AsyncAttrs

__all__ = [
    "UserGroupLink",
    "User",
    "Group",
    "Message",
    "MessageSegment",
    "MediaFile",
    "TABLES",
]

T = TypeVar("T")


class AsyncAttrs(_AsyncAttrs, Generic[T]):
    if TYPE_CHECKING:
        awaitable_attrs: T


class UserGroupLink(SQLModel, AsyncAttrs, table=True):
    user_id: int | None = Field(default=None, primary_key=True, foreign_key="user.id")
    group_id: int | None = Field(default=None, primary_key=True, foreign_key="group.id")


class _UserAwaitableAttrs:
    groups: Awaitable[list["Group"]]
    sent_messages: Awaitable[list["Message"]]
    received_messages: Awaitable[list["Message"]]


class User(SQLModel, AsyncAttrs[_UserAwaitableAttrs], table=True):
    id: int = Field(primary_key=True)
    name: str | None

    groups: list["Group"] = Relationship(
        back_populates="members", link_model=UserGroupLink
    )
    sent_messages: list["Message"] = Relationship(
        back_populates="sender",
        sa_relationship_kwargs={"foreign_keys": "Message.sender_id"},
    )
    received_messages: list["Message"] = Relationship(
        back_populates="receiver",
        sa_relationship_kwargs={"foreign_keys": "Message.receiver_id"},
    )


class _GroupAwaitableAttrs:
    members: Awaitable[list["User"]]
    messages: Awaitable[list["Message"]]


class Group(SQLModel, AsyncAttrs[_GroupAwaitableAttrs], table=True):
    id: int = Field(primary_key=True)
    name: str | None = None
    members: list[User] = Relationship(
        back_populates="groups", link_model=UserGroupLink
    )
    messages: list["Message"] = Relationship(back_populates="group")


class _MsgAwaitableAttrs:
    sender: Awaitable[User]
    group: Awaitable[Group | None]
    receiver: Awaitable[User | None]
    segments: Awaitable["MessageSegment"]


class Message(SQLModel, AsyncAttrs[_MsgAwaitableAttrs], table=True):
    store_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    store_time: float = Field(default_factory=time.time, index=True)
    message_id: int = Field(index=True)
    timestamp: float = Field(index=True)
    message_type: str = Field(default="group")

    sender_id: int = Field(foreign_key="user.id", index=True)
    sender: User = Relationship(
        back_populates="sent_messages",
        sa_relationship_kwargs={"foreign_keys": "Message.sender_id"},
    )

    # 群聊关系（当 message_type=group 时有效）
    group_id: int | None = Field(default=None, foreign_key="group.id", index=True)
    group: Group | None = Relationship(back_populates="messages")

    # 私聊关系（当 message_type=private 时有效）
    receiver_id: int | None = Field(default=None, foreign_key="user.id")
    receiver: User | None = Relationship(
        back_populates="received_messages",
        sa_relationship_kwargs={"foreign_keys": "Message.receiver_id"},
    )

    segments: list["MessageSegment"] = Relationship(
        back_populates="message", sa_relationship_kwargs={"cascade": "all, delete"}
    )

    __table_args__ = (
        CheckConstraint(
            "(message_type = 'group' AND group_id IS NOT NULL AND receiver_id IS NULL) OR "
            "(message_type = 'private' AND receiver_id IS NOT NULL AND group_id IS NULL)",
            name="message_type_check",
        ),
    )


class _MsgSegAwaitableAttrs:
    message: Awaitable[Message]


class MessageSegment(SQLModel, AsyncAttrs[_MsgSegAwaitableAttrs], table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order: int = Field(ge=0)

    type: str
    data: dict[str, Any] = Field(sa_column=Column(JSON))

    message_store_id: uuid.UUID = Field(foreign_key="message.store_id")
    message: Message = Relationship(back_populates="segments")


class MediaFile(SQLModel, AsyncAttrs, table=True):
    fileid: str = Field(primary_key=True)
    timestamp: float = Field(default_factory=time.time)
    # 在下载完成前用 None 占位
    path: str | None = None
    hash: str | None = None


TABLES = [
    SQLModel.metadata.tables[t.__tablename__]
    for t in (UserGroupLink, User, Group, Message, MessageSegment, MediaFile)
]
