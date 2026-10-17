"""事件留档: 收到的每一报 (含原文) 与每一次推送的结果写入 sqlite.

用途:
- 重启后恢复去重状态, 避免同一报或同一事件被重复推送
- 为以后的历史查询留数据 (查询本身尚未实现)

所有时间以 UTC 存储. SQLite 读回的 datetime 不带时区, 读取时按 UTC 补上.
留档失败不能影响推送: 调用方捕获异常后照常推送.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from lemony_storage_helper.database.utils import datetime_column_tzaware, queryable
from sqlalchemy import Column, Index, Text, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, select
from uuid_utils.compat import uuid7

from .quake import Quake
from .subscription import TargetKey, TargetType

__all__ = [
    "AlertArchive",
    "AlertDelivery",
    "AlertReport",
    "DeliveryResult",
    "RestoredDelivery",
    "alerts_metadata",
]

logger = logging.getLogger(__name__)

AlertsBase, _, alerts_metadata = SqliteDatabaseHelper.new_base("Alerts")


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _target_type(value: str) -> TargetType:
    if value == "group":
        return "group"
    if value == "private":
        return "private"
    raise ValueError(f"未知推送目标类型: {value!r}")


class AlertReport(AlertsBase, table=True):
    """一报: (数据源, 事件, 报数) 唯一"""

    __tablename__ = "alert_report"

    id: uuid.UUID = Field(default_factory=uuid7, primary_key=True)
    received_at: datetime = Field(
        default_factory=_now,
        sa_column=datetime_column_tzaware(default=_now, index=True),
    )
    source: str = Field(index=True)
    event_id: str
    seq: int
    kind: str = Field(index=True, description="eew | report")
    report_time: datetime = Field(sa_column=datetime_column_tzaware())
    origin_time: datetime = Field(sa_column=datetime_column_tzaware(index=True))
    hypocenter: str
    latitude: float | None = None
    longitude: float | None = None
    magnitude: float | None = Field(default=None, index=True)
    depth: float | None = None
    intensity: float | None = None
    shindo: str | None = None
    is_final: bool = False
    is_cancel: bool = False
    is_training: bool = False
    raw: str = Field(sa_column=Column(Text, nullable=False), description="报文原文")

    __table_args__ = (
        UniqueConstraint("source", "event_id", "seq", name="uq_alert_report_key"),
        Index("ix_alert_report_event", "source", "event_id"),
    )


class AlertDelivery(AlertsBase, table=True):
    """一次推送尝试"""

    __tablename__ = "alert_delivery"

    id: uuid.UUID = Field(default_factory=uuid7, primary_key=True)
    report_id: uuid.UUID = Field(foreign_key="alert_report.id", index=True)
    target_type: str
    target_id: int
    sent_at: datetime = Field(
        default_factory=_now,
        sa_column=datetime_column_tzaware(default=_now, index=True),
    )
    ok: bool
    error: str | None = None

    __table_args__ = (Index("ix_alert_delivery_target", "target_type", "target_id"),)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    target: TargetKey
    ok: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RestoredDelivery:
    target: TargetKey
    event_key: tuple[str, str]
    seq: int
    final: bool
    at: datetime


class AlertArchive:
    def __init__(self, db: SqliteDatabaseHelper) -> None:
        self._db = db

    async def record_report(self, quake: Quake, raw: str) -> uuid.UUID | None:
        """写入一报; 已存在时返回 None (重复报文)"""
        report = AlertReport(
            source=quake.source,
            event_id=quake.event_id,
            seq=quake.seq,
            kind=quake.kind,
            report_time=_as_utc(quake.report_time),
            origin_time=_as_utc(quake.origin_time),
            hypocenter=quake.hypocenter,
            latitude=quake.latitude,
            longitude=quake.longitude,
            magnitude=quake.magnitude,
            depth=quake.depth,
            intensity=quake.intensity,
            shindo=quake.shindo,
            is_final=quake.is_final,
            is_cancel=quake.is_cancel,
            is_training="训练" in quake.extra_tags,
            raw=raw,
        )
        try:
            async with self._db.session_scope() as session:
                session.add(report)
        except IntegrityError:
            return None
        return report.id

    async def record_deliveries(
        self, report_id: uuid.UUID, results: Sequence[DeliveryResult]
    ) -> None:
        if not results:
            return
        async with self._db.session_scope() as session:
            session.add_all(
                AlertDelivery(
                    report_id=report_id,
                    target_type=r.target[0],
                    target_id=r.target[1],
                    ok=r.ok,
                    error=r.error,
                )
                for r in results
            )

    async def recent_report_keys(
        self, since: datetime
    ) -> list[tuple[tuple[str, str, int], datetime]]:
        """``since`` 之后收到过的报 (用于恢复 "这一报已处理")"""
        async with self._db.get_session() as session:
            stmt = select(
                AlertReport.source,
                AlertReport.event_id,
                AlertReport.seq,
                AlertReport.received_at,
            ).where(AlertReport.received_at >= _as_utc(since))
            rows = (await session.exec(stmt)).all()
        return [((s, e, q), _as_utc(at)) for s, e, q, at in rows]

    async def recent_deliveries(self, since: datetime) -> list[RestoredDelivery]:
        """``since`` 之后的推送尝试 (用于恢复 "这个会话已收到过该事件")"""
        async with self._db.get_session() as session:
            stmt = (
                select(AlertDelivery, AlertReport)
                .join(
                    AlertReport,
                    queryable(AlertDelivery.report_id) == queryable(AlertReport.id),
                )
                .where(AlertDelivery.sent_at >= _as_utc(since))
            )
            rows = (await session.exec(stmt)).all()
        return [
            RestoredDelivery(
                target=(_target_type(d.target_type), d.target_id),
                event_key=(r.source, r.event_id),
                seq=r.seq,
                final=r.is_final or r.is_cancel,
                at=_as_utc(d.sent_at),
            )
            for d, r in rows
        ]

    async def reports_of_event(self, source: str, event_id: str) -> list[AlertReport]:
        async with self._db.get_session() as session:
            stmt = (
                select(AlertReport)
                .where(AlertReport.source == source, AlertReport.event_id == event_id)
                .order_by(queryable(AlertReport.seq))
            )
            return list((await session.exec(stmt)).all())
