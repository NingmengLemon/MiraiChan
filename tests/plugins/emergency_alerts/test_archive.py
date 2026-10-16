"""事件留档: 写入、去重、重启后恢复去重状态."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from mbplugin_emergency_alerts.archive import (
    AlertArchive,
    DeliveryResult,
    alerts_metadata,
)
from mbplugin_emergency_alerts.dispatch import Dispatcher
from mbplugin_emergency_alerts.quake import CST, Quake
from mbplugin_emergency_alerts.sources.wolfx import parse_message
from mbplugin_emergency_alerts.subscription import Subscription
from wolfx_samples import cenc_eew, jma_eew

NOW = datetime(2026, 10, 16, 12, 0, 30, tzinfo=CST)
GROUP = ("group", 1)


def q(raw) -> Quake:
    got = parse_message(raw)
    assert got is not None
    return got


@pytest_asyncio.fixture
async def archive(tmp_path):
    db = SqliteDatabaseHelper("alerts.db", alerts_metadata, relative_path_base=tmp_path)
    await db.startup()
    try:
        yield AlertArchive(db)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_records_every_field_and_the_raw_text(archive):
    raw = cenc_eew()
    report_id = await archive.record_report(q(raw), json.dumps(raw, ensure_ascii=False))
    assert report_id is not None
    (row,) = await archive.reports_of_event("cenc_eew", raw["EventID"])
    assert (row.seq, row.kind, row.hypocenter, row.magnitude) == (
        1,
        "eew",
        "四川雅安市宝兴县",
        5.2,
    )
    assert json.loads(row.raw) == raw


@pytest.mark.asyncio
async def test_times_are_stored_as_utc(archive):
    await archive.record_report(q(jma_eew()), "{}")
    (row,) = await archive.reports_of_event("jma_eew", jma_eew()["EventID"])
    # 13:00:05 JST == 04:00:05 UTC; SQLite 读回不带时区, 存的是 UTC
    assert row.origin_time.replace(tzinfo=UTC) == datetime(
        2026, 10, 16, 4, 0, 5, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_duplicate_report_is_not_stored_twice(archive):
    assert await archive.record_report(q(cenc_eew()), "{}") is not None
    assert await archive.record_report(q(cenc_eew()), "{}") is None
    assert len(await archive.reports_of_event("cenc_eew", cenc_eew()["EventID"])) == 1


@pytest.mark.asyncio
async def test_training_flag_is_kept(archive):
    await archive.record_report(q(jma_eew(isTraining=True)), "{}")
    (row,) = await archive.reports_of_event("jma_eew", jma_eew()["EventID"])
    assert row.is_training


@pytest.mark.asyncio
async def test_recent_queries_respect_the_cutoff(archive):
    report_id = await archive.record_report(q(cenc_eew()), "{}")
    assert report_id is not None
    await archive.record_deliveries(
        report_id,
        [
            DeliveryResult(GROUP, ok=True),
            DeliveryResult(("private", 2), ok=False, error="x"),
        ],
    )
    past = datetime.now(UTC) - timedelta(minutes=1)
    future = datetime.now(UTC) + timedelta(minutes=1)
    assert [k for k, _ in await archive.recent_report_keys(past)] == [
        ("cenc_eew", cenc_eew()["EventID"], 1)
    ]
    assert await archive.recent_report_keys(future) == []
    restored = await archive.recent_deliveries(past)
    assert sorted(d.target for d in restored) == [GROUP, ("private", 2)]
    assert all(d.event_key == ("cenc_eew", cenc_eew()["EventID"]) for d in restored)
    assert all(d.at.tzinfo is UTC for d in restored)


@pytest.mark.asyncio
async def test_restored_state_prevents_repeats_after_restart(archive):
    """模拟重启: 新的 Dispatcher 从留档恢复后, 同一报不再推, 同一事件按策略不再推"""
    sub = Subscription(target_type="group", target_id=1, updates="first")
    first = q(cenc_eew())
    report_id = await archive.record_report(first, "{}")
    assert report_id is not None
    await archive.record_deliveries(report_id, [DeliveryResult(GROUP, ok=True)])

    restarted = Dispatcher(now=lambda: NOW)
    since = datetime.now(UTC) - timedelta(days=1)
    for key, at in await archive.recent_report_keys(since):
        restarted.restore_seen(key, at)
    for d in await archive.recent_deliveries(since):
        restarted.restore_pushed(
            d.target, d.event_key, seq=d.seq, final=d.final, at=d.at
        )

    assert restarted.select(first, [sub]) == []
    assert restarted.select(q(cenc_eew(ReportNum=2)), [sub]) == []
    # 取消报仍然会发给收到过该事件的会话
    assert restarted.select(q(cenc_eew(ReportNum=3, isCancel=True)), [sub]) == [sub]


def test_without_restore_the_same_report_would_be_pushed_again():
    """阳性对照: 不恢复状态时, 新 Dispatcher 会再推一次"""
    sub = Subscription(target_type="group", target_id=1)
    assert Dispatcher(now=lambda: NOW).select(q(cenc_eew()), [sub]) == [sub]
