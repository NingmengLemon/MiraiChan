"""引用图存档: 文件落盘 + sqlite 索引。

文件名不承载元数据, 元数据都在索引里。存档写入失败不影响已经发出的图。
写入完成后依次调用已注册的回调 (例如以后接群文件上传)。
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from lemony_storage_helper.database.utils import datetime_column_tzaware
from sqlalchemy import Column, Index, String
from sqlmodel import Field, select
from uuid_utils.compat import uuid7

__all__ = [
    "ArchiveRecord",
    "ArchivedHook",
    "QuoteArchive",
    "QuoteArtifact",
    "quote_metadata",
]

logger = logging.getLogger(__name__)

QuoteBase, _, quote_metadata = SqliteDatabaseHelper.new_base("Quote")


def _now() -> datetime:
    return datetime.now(UTC)


class QuoteArtifact(QuoteBase, table=True):
    __tablename__ = "quote_artifact"

    id: uuid.UUID = Field(default_factory=uuid7, primary_key=True)
    created_at: datetime = Field(
        default_factory=_now,
        sa_column=datetime_column_tzaware(default=_now, index=True),
    )
    style: str = Field(index=True, description="card | chat")
    group_id: int = Field(index=True)
    requester_id: int = Field(index=True)
    base_message_id: str = Field(index=True)
    range_start: int = 0
    range_end: int = 0
    sender_only: bool = False
    scale: float = 1.0
    sender_ids: str = Field(default="[]", description="JSON 数组")
    path: str = Field(description="相对存档根目录")
    format: str
    sha256: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    size: int
    width: int
    height: int
    sent_message_id: str | None = Field(
        default=None,
        index=True,
        description="bot 发出的那条图片消息的 id, 用于回复定位",
    )

    __table_args__ = (Index("ix_quote_artifact_group_time", "group_id", "created_at"),)


@dataclass(frozen=True, slots=True)
class ArchiveRecord:
    style: str
    group_id: int
    requester_id: int
    base_message_id: str
    range_start: int
    range_end: int
    sender_only: bool
    scale: float
    sender_ids: Sequence[int]
    width: int
    height: int


ArchivedHook = Callable[[QuoteArtifact, Path], Awaitable[None]]


class QuoteArchive:
    """``root`` 下按年月分目录存文件, 索引库由 ``db`` 管理"""

    def __init__(self, db: SqliteDatabaseHelper, root: Path) -> None:
        self._db = db
        self._root = root
        self._hooks: list[ArchivedHook] = []

    @property
    def root(self) -> Path:
        return self._root

    def add_hook(self, hook: ArchivedHook) -> None:
        self._hooks.append(hook)

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "wb") as fp:
                fp.write(data)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    async def save(self, record: ArchiveRecord, data: bytes, fmt: str) -> QuoteArtifact:
        artifact_id = uuid7()
        now = _now()
        rel = Path(f"{now:%Y}") / f"{now:%m}" / f"{artifact_id.hex}.{fmt}"
        await asyncio.to_thread(self._write_atomic, self._root / rel, data)
        artifact = QuoteArtifact(
            id=artifact_id,
            created_at=now,
            style=record.style,
            group_id=record.group_id,
            requester_id=record.requester_id,
            base_message_id=record.base_message_id,
            range_start=record.range_start,
            range_end=record.range_end,
            sender_only=record.sender_only,
            scale=record.scale,
            sender_ids=json.dumps(list(record.sender_ids)),
            path=rel.as_posix(),
            format=fmt,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            width=record.width,
            height=record.height,
        )
        try:
            async with self._db.get_session() as session, session.begin():
                session.add(artifact)
        except Exception:
            # 索引没写进去的文件留着也找不到, 删掉
            (self._root / rel).unlink(missing_ok=True)
            raise
        for hook in self._hooks:
            try:
                await hook(artifact, self._root / rel)
            except Exception:
                logger.exception("存档回调失败: %s", hook)
        return artifact

    async def attach_sent_message(
        self, artifact_id: uuid.UUID, message_id: str
    ) -> None:
        async with self._db.get_session() as session, session.begin():
            artifact = await session.get(QuoteArtifact, artifact_id)
            if artifact is not None:
                artifact.sent_message_id = message_id

    async def find_by_sent_message(self, message_id: str) -> QuoteArtifact | None:
        async with self._db.get_session() as session:
            stmt = select(QuoteArtifact).where(
                QuoteArtifact.sent_message_id == message_id
            )
            return (await session.exec(stmt)).first()

    async def delete(self, artifact_id: uuid.UUID) -> bool:
        """删除索引与文件, 不存在时返回 False"""
        async with self._db.get_session() as session, session.begin():
            artifact = await session.get(QuoteArtifact, artifact_id)
            if artifact is None:
                return False
            path = self._root / artifact.path
            await session.delete(artifact)
        await asyncio.to_thread(path.unlink, missing_ok=True)
        return True
