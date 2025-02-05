import time
from typing import Any
import uuid

from sqlmodel import Relationship, SQLModel, Field, JSON, CheckConstraint
from sqlalchemy import Column

__all__ = [
    "UserGroupLink",
    "User",
    "Group",
    "Message",
    "MessageSegment",
    "Image",
    "TABLES",
]


class UserGroupLink(SQLModel, table=True):
    user_id: int | None = Field(default=None, primary_key=True, foreign_key="user.id")
    group_id: int | None = Field(default=None, primary_key=True, foreign_key="group.id")


class User(SQLModel, table=True):
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


class Group(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str | None = None
    members: list[User] = Relationship(
        back_populates="groups", link_model=UserGroupLink
    )
    messages: list["Message"] = Relationship(back_populates="group")


class Message(SQLModel, table=True):
    store_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    message_id: int = Field(index=True)
    timestamp: float = Field(default_factory=time.time, index=True)
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


class MessageSegment(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order: int = Field(ge=0)

    type: str
    data: dict[str, Any] = Field(sa_column=Column(JSON))

    message_store_id: uuid.UUID = Field(foreign_key="message.store_id")
    message: Message = Relationship(back_populates="segments")


class Image(SQLModel, table=True):
    fileid: str = Field(primary_key=True)
    timestamp: float = Field(default_factory=time.time)
    # 在下载完成前用 None 占位
    path: str | None = None
    hash: str | None = None


TABLES = [
    SQLModel.metadata.tables[t.__tablename__]
    for t in (UserGroupLink, User, Group, Message, MessageSegment, Image)
]


def test():
    from sqlmodel import create_engine, Session
    import os

    db = "testrecorder.db"
    if os.path.exists(db):
        os.remove(db)
    engine = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as sess:
        u1 = User(id=45450721, name="Koharu")
        u2 = User(id=161127, name="Hifumi")
        g = Group(id=123456, name="Supplementary Classes Club")
        g.members = [u1, u2]
        msg1 = Message(
            message_id=1,
            message_type="group",
            sender=u1,
            group=g,
            segments=[
                MessageSegment(
                    order=0, type="text", data={"content": "Hello, everyone!"}
                ),
                MessageSegment(
                    order=1, type="image", data={"url": "http://example.com/image.png"}
                ),
            ],
        )

        msg2 = Message(
            message_id=2,
            message_type="private",
            sender=u2,
            receiver=u1,
            segments=[
                MessageSegment(order=0, type="text", data={"content": "Hi, Koharu!"})
            ],
        )

        sess.add_all([u1, u2, g, msg1, msg2])
        sess.commit()
