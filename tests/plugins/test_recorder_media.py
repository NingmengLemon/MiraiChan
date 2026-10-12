"""recorder 媒体下载队列: 退避、放弃、优先级、中断回收, 以及 schema 迁移。"""

import sqlite3
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from aiohttp import ClientResponseError, RequestInfo
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from mbplugin_recorder.db.dto import (
    AccountInput,
    ConversationInput,
    IdentityInput,
    MediaSourceInput,
    MessageSegmentInput,
    RecordedMessageInput,
)
from mbplugin_recorder.db.enums import MediaDownloadStatus
from mbplugin_recorder.db.models import MediaSource, recorder_metadata
from mbplugin_recorder.db.operations import (
    list_pending_media_sources,
    mark_media_source_downloading,
    mark_media_source_failed,
    reclaim_stale_downloading,
    record_message,
    retry_delay,
)
from mbplugin_recorder.migration import migrate
from mbplugin_recorder.worker import is_permanent_failure
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _payload(mid: str, file_ids: list[str]) -> RecordedMessageInput:
    account = AccountInput(protocol="p", self_id="1")
    return RecordedMessageInput(
        account=account,
        conversation=ConversationInput(type="group", external_id="2"),
        sender=IdentityInput(
            protocol="p", namespace="user", external_id="3", account=account
        ),
        external_message_id=mid,
        sent_at=T0,
        segments=[
            MessageSegmentInput(
                type="image",
                data={"file": f},
                media_sources=(
                    MediaSourceInput(
                        source_file_id=f, media_type="image", url=f"https://x/{f}"
                    ),
                ),
            )
            for f in file_ids
        ],
    )


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[SqliteDatabaseHelper]:
    helper = SqliteDatabaseHelper(
        "r.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    await helper.startup(prepare=migrate)
    try:
        yield helper
    finally:
        await helper.close()


async def _pending_ids(db: SqliteDatabaseHelper, now=None) -> list[str]:
    async with db.get_session(style="sqlalchemy") as s:
        return [m.source_file_id for m in await list_pending_media_sources(s, now=now)]


async def _get(db: SqliteDatabaseHelper, file_id: str) -> MediaSource:
    async with db.get_session(style="sqlalchemy") as s:
        for m in await list_pending_media_sources(
            s, limit=100, now=datetime(2100, 1, 1, tzinfo=UTC)
        ):
            if m.source_file_id == file_id:
                return m
        from sqlalchemy import select

        return (
            await s.execute(select(MediaSource).where(MediaSource.source_file_id == file_id))
        ).scalar_one()


def test_retry_delay_is_capped_exponential() -> None:
    delays = [retry_delay(n, base=60, cap=3600).total_seconds() for n in range(1, 6)]
    assert delays == [60, 240, 960, 3600, 3600]


def test_permanent_failures() -> None:
    info = RequestInfo(URL("https://x"), "GET", CIMultiDictProxy(CIMultiDict()))
    assert is_permanent_failure(ClientResponseError(info, (), status=403))
    assert not is_permanent_failure(ClientResponseError(info, (), status=503))
    assert not is_permanent_failure(TimeoutError())


@pytest.mark.asyncio
async def test_failed_sources_back_off_and_do_not_block_new_ones(
    db: SqliteDatabaseHelper,
) -> None:
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["old"]))
    old = await _get(db, "old")
    async with db.get_session(style="sqlalchemy") as s:
        await mark_media_source_downloading(s, old.id)
        await mark_media_source_failed(s, old.id, "503", retry_base=60)
    # 退避期内不出现
    assert await _pending_ids(db) == []
    later = datetime.now(UTC) + timedelta(seconds=61)
    assert await _pending_ids(db, now=later) == ["old"]

    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m2", ["new"]))
    # 新的 PENDING 排在到期的 FAILED 前面
    assert await _pending_ids(db, now=later) == ["new", "old"]


@pytest.mark.asyncio
async def test_abandon_after_max_attempts_or_permanent(db: SqliteDatabaseHelper) -> None:
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["a", "b"]))
    a, b = await _get(db, "a"), await _get(db, "b")
    async with db.get_session(style="sqlalchemy") as s:
        for _ in range(3):
            await mark_media_source_downloading(s, a.id)
            await mark_media_source_failed(s, a.id, "x", max_attempts=3, retry_base=0)
        await mark_media_source_downloading(s, b.id)
        await mark_media_source_failed(s, b.id, "403", permanent=True)
    assert (await _get(db, "a")).download_status is MediaDownloadStatus.ABANDONED
    assert (await _get(db, "a")).attempt_count == 3
    assert (await _get(db, "b")).download_status is MediaDownloadStatus.ABANDONED
    assert await _pending_ids(db, now=datetime(2100, 1, 1, tzinfo=UTC)) == []


@pytest.mark.asyncio
async def test_reclaim_stale_downloading(db: SqliteDatabaseHelper) -> None:
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["a"]))
    a = await _get(db, "a")
    async with db.get_session(style="sqlalchemy") as s:
        await mark_media_source_downloading(s, a.id)
        assert await reclaim_stale_downloading(s, older_than=timedelta(hours=1)) == 0
        assert await reclaim_stale_downloading(s, older_than=timedelta(seconds=-1)) == 1
    assert (await _get(db, "a")).download_status is MediaDownloadStatus.FAILED
    assert await _pending_ids(db) == ["a"]


LEGACY_SCHEMA = """
CREATE TABLE recorder_media_source (
    id CHAR(32) NOT NULL PRIMARY KEY, source_file_id VARCHAR NOT NULL,
    media_type VARCHAR NOT NULL, url VARCHAR, download_status VARCHAR(11) NOT NULL,
    download_error VARCHAR, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
    account_id CHAR(32) NOT NULL, media_object_id CHAR(32)
);
CREATE TABLE recorder_media_object (
    id CHAR(32) NOT NULL PRIMARY KEY, sha256 VARCHAR, md5 VARCHAR, size INTEGER,
    mime_type VARCHAR, media_type VARCHAR NOT NULL, cache_path VARCHAR,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
);
INSERT INTO recorder_media_object VALUES
    ('a', NULL, NULL, NULL, NULL, 'image', 'data/record/media/image/x.png', '2026-01-01', '2026-01-01'),
    ('b', NULL, NULL, NULL, NULL, 'image', 'record/media/image/y.png', '2026-01-01', '2026-01-01'),
    ('c', NULL, NULL, NULL, NULL, 'image', 'data/record/mediaX/z.png', '2026-01-01', '2026-01-01');
"""


@pytest.mark.asyncio
async def test_migration_adds_columns_and_rebases_paths(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.commit()
    conn.close()

    helper = SqliteDatabaseHelper(
        "legacy.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    done: list[list[str]] = []
    await helper.startup(prepare=lambda c: done.append(migrate(c)))
    await helper.close()
    assert any("attempt_count" in d for d in done[0])

    conn = sqlite3.connect(path)
    try:
        cols = {r[1] for r in conn.execute("pragma table_info(recorder_media_source)")}
        paths = dict(conn.execute("select id, cache_path from recorder_media_object"))
    finally:
        conn.close()
    assert {"attempt_count", "next_attempt_at"} <= cols
    assert paths == {
        "a": "record/media/image/x.png",
        "b": "record/media/image/y.png",
        "c": "data/record/mediaX/z.png",
    }

    # 第二次是空操作
    helper = SqliteDatabaseHelper(
        "legacy.db", metadata=recorder_metadata, relative_path_base=tmp_path
    )
    again: list[list[str]] = []
    await helper.startup(prepare=lambda c: again.append(migrate(c)))
    await helper.close()
    assert again == [[]]
