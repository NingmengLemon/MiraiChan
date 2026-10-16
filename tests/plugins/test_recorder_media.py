"""recorder 媒体下载队列: 退避、放弃、优先级、中断回收、取消清理, 以及 schema 迁移。"""

import asyncio
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
from lemony_storage_helper.database import queryable
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
    mark_media_source_downloaded,
    mark_media_source_downloading,
    mark_media_source_failed,
    reclaim_stale_downloading,
    record_message,
    retry_delay,
)
from mbplugin_recorder.media import download_media_source
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
            await s.execute(
                select(MediaSource).where(
                    queryable(MediaSource.source_file_id) == file_id
                )
            )
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
async def test_abandon_after_max_attempts_or_permanent(
    db: SqliteDatabaseHelper,
) -> None:
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
async def test_run_once_persists_status_changes(
    db: SqliteDatabaseHelper, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归: worker 先 SELECT 再写, 状态必须真正落库 (曾经全部被回滚)"""
    from mbplugin_recorder import worker as worker_mod

    payload = MediaSourceInput(
        source_file_id="ok",
        media_type="image",
        url="https://x/ok",
        download_status=MediaDownloadStatus.DOWNLOADED,
        sha256="a" * 64,
        size=3,
        cache_path="record/media/image/ok.png",
    )

    async def fake_download(session, source, *, root, data_root=None, max_bytes=0):
        if source.source_file_id == "bad":
            raise RuntimeError("nope")
        return payload

    monkeypatch.setattr(worker_mod, "download_media_source", fake_download)
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["ok", "bad"]))

    w = worker_mod.MediaDownloadWorker(db, data_root=None, retry_base=0, max_attempts=2)
    await w.run_once(http_session=None)  # ty: ignore[invalid-argument-type]

    assert (await _get(db, "ok")).download_status is MediaDownloadStatus.DOWNLOADED
    bad = await _get(db, "bad")
    assert bad.download_status is MediaDownloadStatus.FAILED
    assert bad.attempt_count == 1
    # 已下载的不再出现在待处理里; 失败的在退避 (retry_base=0 时立刻可重试)
    assert await _pending_ids(db) == ["bad"]


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


@pytest.mark.asyncio
async def test_run_once_reclaims_orphaned_downloading(
    db: SqliteDatabaseHelper, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归: 崩溃后很快重启留下的 DOWNLOADING 不会再被永久漏掉.

    旧实现只在启动时回收一次, 且要求行已超过 request_timeout。崩溃后很快重启
    (间隔小于 request_timeout) 的行既不在待下载列表里, 也没被回收, 就此永远卡住。
    """
    from mbplugin_recorder import worker as worker_mod

    payload = MediaSourceInput(
        source_file_id="orphan",
        media_type="image",
        url="https://x/orphan",
        download_status=MediaDownloadStatus.DOWNLOADED,
        sha256="a" * 64,
        size=3,
        cache_path="record/media/image/orphan.png",
    )
    downloaded: list[str] = []

    async def fake_download(session, source, *, root, data_root=None, max_bytes=0):
        downloaded.append(source.source_file_id)
        return payload

    monkeypatch.setattr(worker_mod, "download_media_source", fake_download)
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["orphan"]))
    orphan = await _get(db, "orphan")
    async with db.get_session(style="sqlalchemy") as s:
        await mark_media_source_downloading(s, orphan.id)  # 模拟下载中进程退出
    # DOWNLOADING 不在待下载列表里, 只有回收能把它放回来
    assert await _pending_ids(db) == []

    w = worker_mod.MediaDownloadWorker(db, data_root=None, request_timeout=-1)
    await w.run_once(http_session=None)  # ty: ignore[invalid-argument-type]

    assert downloaded == ["orphan"]
    assert (await _get(db, "orphan")).download_status is MediaDownloadStatus.DOWNLOADED


@pytest.mark.asyncio
async def test_run_once_keeps_fresh_downloading(
    db: SqliteDatabaseHelper, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正在下载的行 (updated_at 新鲜) 不能被回收后重复下载."""
    from mbplugin_recorder import worker as worker_mod

    downloaded: list[str] = []

    async def fake_download(session, source, *, root, data_root=None, max_bytes=0):
        downloaded.append(source.source_file_id)
        raise AssertionError("正在下载的行不应该被再次下载")

    monkeypatch.setattr(worker_mod, "download_media_source", fake_download)
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["busy"]))
    busy = await _get(db, "busy")
    async with db.get_session(style="sqlalchemy") as s:
        await mark_media_source_downloading(s, busy.id)

    w = worker_mod.MediaDownloadWorker(db, data_root=None, request_timeout=120)
    await w.run_once(http_session=None)  # ty: ignore[invalid-argument-type]

    assert downloaded == []
    assert (await _get(db, "busy")).download_status is MediaDownloadStatus.DOWNLOADING


def _downloaded(file_id: str, url: str) -> MediaSourceInput:
    """构造一个"已下载"来源的输入 (用于直接标记下载完成)."""
    return MediaSourceInput(
        source_file_id=file_id,
        media_type="image",
        url=url,
        download_status=MediaDownloadStatus.DOWNLOADED,
        sha256="f" * 64,
        size=7,
        cache_path=f"record/media/image/{file_id}.png",
    )


def _payload_urls(mid: str, pairs: list[tuple[str, str]]) -> RecordedMessageInput:
    """会话/发送者固定、但每条媒体来源的链接可控的消息输入."""
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
                data={"file": file_id},
                media_sources=(
                    MediaSourceInput(
                        source_file_id=file_id, media_type="image", url=url
                    ),
                ),
            )
            for file_id, url in pairs
        ],
    )


@pytest.mark.asyncio
async def test_rereport_does_not_reset_downloaded_status(
    db: SqliteDatabaseHelper,
) -> None:
    """回归: 同一个 file_id 出现在新消息里时, 已下载的记录不得退回待下载."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["img"]))
    img = await _get(db, "img")
    async with db.get_session(style="sqlalchemy") as s:
        await mark_media_source_downloading(s, img.id)
        await mark_media_source_downloaded(
            s, img.id, _downloaded("img", "https://x/img")
        )

    # 另一条消息引用了同一个 file_id (转发、重发)
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m2", ["img"]))

    assert (await _get(db, "img")).download_status is MediaDownloadStatus.DOWNLOADED
    assert await _pending_ids(db) == []


@pytest.mark.asyncio
async def test_rereport_keeps_downloading_status(db: SqliteDatabaseHelper) -> None:
    """正在下载的记录也不能被重报退回待下载 (会重复下载)."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["busy"]))
    busy = await _get(db, "busy")
    async with db.get_session(style="sqlalchemy") as s:
        await mark_media_source_downloading(s, busy.id)
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m2", ["busy"]))

    assert (await _get(db, "busy")).download_status is MediaDownloadStatus.DOWNLOADING


@pytest.mark.asyncio
async def test_abandoned_source_revives_only_with_new_url(
    db: SqliteDatabaseHelper,
) -> None:
    """已放弃的来源: 同一个死链接重报不复活, 换上新链接才重新排队."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["dead"]))
    dead = await _get(db, "dead")
    async with db.get_session(style="sqlalchemy") as s:
        await mark_media_source_downloading(s, dead.id)
        await mark_media_source_failed(s, dead.id, "403", permanent=True)
    assert (await _get(db, "dead")).download_status is MediaDownloadStatus.ABANDONED

    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m2", ["dead"]))
    assert (await _get(db, "dead")).download_status is MediaDownloadStatus.ABANDONED
    assert await _pending_ids(db) == []

    async with db.get_session(style="sqlalchemy") as s:
        await record_message(
            s, _payload_urls("m3", [("dead", "https://x/dead?token=new")])
        )
    revived = await _get(db, "dead")
    assert revived.download_status is MediaDownloadStatus.PENDING
    assert revived.attempt_count == 0
    assert revived.next_attempt_at is None
    assert await _pending_ids(db) == ["dead"]


class _FakeContent:
    """按块产出内容, 可在第 N 块之后抛 CancelledError (模拟进程停止时取消下载)."""

    def __init__(self, chunks: list[bytes], cancel_after: int | None = None) -> None:
        self._chunks = chunks
        self._cancel_after = cancel_after

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for index, chunk in enumerate(self._chunks):
            yield chunk
            if self._cancel_after is not None and index + 1 == self._cancel_after:
                raise asyncio.CancelledError


class _FakeResponse:
    def __init__(self, chunks: list[bytes], *, cancel_after: int | None = None) -> None:
        self.content = _FakeContent(chunks, cancel_after)
        self.content_length: int | None = None

    def raise_for_status(self) -> None:
        return None


class _FakeGet:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def get(self, url: str, **kwargs: object) -> _FakeGet:
        return _FakeGet(self._response)


@pytest.mark.asyncio
async def test_cancelled_download_cleans_up_tmp_file(
    db: SqliteDatabaseHelper, tmp_path: Path
) -> None:
    """回归: 取消 (CancelledError) 不是 Exception, 旧的清理分支漏掉了它.

    进程停止时 worker.stop() 会取消正在下载的任务, 于是每次重启都在媒体目录里留下
    一个 .download 半成品。
    """
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["img"]))
    source = await _get(db, "img")
    session = _FakeSession(_FakeResponse([b"abc", b"def"], cancel_after=1))

    with pytest.raises(asyncio.CancelledError):
        await download_media_source(
            session,  # ty: ignore[invalid-argument-type]
            source,
            root="media",
            data_root=tmp_path,
        )

    assert list((tmp_path / "media").rglob("*.download")) == []


@pytest.mark.asyncio
async def test_successful_download_leaves_no_tmp_file(
    db: SqliteDatabaseHelper, tmp_path: Path
) -> None:
    """正常下载: 临时文件被改名成最终文件, 不残留 .download."""
    async with db.get_session(style="sqlalchemy") as s:
        await record_message(s, _payload("m1", ["img"]))
    source = await _get(db, "img")
    session = _FakeSession(_FakeResponse([b"abc", b"def"]))

    payload = await download_media_source(
        session,  # ty: ignore[invalid-argument-type]
        source,
        root="media",
        data_root=tmp_path,
    )

    assert payload.download_status is MediaDownloadStatus.DOWNLOADED
    assert payload.size == 6
    assert list((tmp_path / "media").rglob("*.download")) == []
    assert payload.cache_path is not None
    assert (tmp_path / payload.cache_path).is_file()


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
