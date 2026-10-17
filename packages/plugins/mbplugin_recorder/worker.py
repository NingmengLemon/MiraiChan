import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

from aiohttp import ClientResponseError, ClientSession, ClientTimeout
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper

from .db.operations import (
    list_pending_media_sources,
    mark_media_source_downloaded,
    mark_media_source_downloading,
    mark_media_source_failed,
    reclaim_stale_downloading,
)
from .media import DEFAULT_MAX_MEDIA_BYTES, download_media_source

logger = logging.getLogger(__name__)

# 这些状态码重试也不会好 (QQ 图床链接过期后返回 4xx)
_PERMANENT_STATUS = frozenset({400, 401, 403, 404, 410})


def is_permanent_failure(exc: BaseException) -> bool:
    return isinstance(exc, ClientResponseError) and exc.status in _PERMANENT_STATUS


class MediaDownloadWorker:
    def __init__(
        self,
        db: SqliteDatabaseHelper,
        *,
        cache_root: str = "record/media",
        data_root: Path | None = None,
        interval: float = 10.0,
        batch_size: int = 10,
        max_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
        request_timeout: float = 120.0,
        max_attempts: int = 5,
        retry_base: float = 60.0,
        retry_cap: float = 6 * 3600.0,
    ) -> None:
        """cache_root 相对 data_root; data_root 为 None 时相对当前目录"""
        self.db = db
        self.cache_root = cache_root
        self.data_root = data_root
        self.interval = interval
        self.batch_size = batch_size
        self.max_bytes = max_bytes
        self.request_timeout = request_timeout
        self.max_attempts = max_attempts
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run())
            logger.info(
                f"媒体下载 worker 已启动: root={self.cache_root}, "
                f"interval={self.interval}, batch_size={self.batch_size}, "
                f"max_bytes={self.max_bytes}, max_attempts={self.max_attempts}"
            )
        else:
            logger.debug("媒体下载 worker 已在运行，跳过重复启动")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("媒体下载 worker 已停止")

    async def _run(self) -> None:
        try:
            await self.db.wait_until_initialized()
        except Exception:
            logger.exception("媒体下载 worker 启动失败, 不再下载媒体")
            return
        timeout = ClientTimeout(total=self.request_timeout)
        async with ClientSession(timeout=timeout) as http_session:
            while not self._stop_event.is_set():
                try:
                    await self.run_once(http_session)
                except Exception:
                    logger.exception("媒体下载 worker 执行失败")
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.interval
                    )

    async def run_once(self, http_session: ClientSession) -> None:
        await self.db.wait_until_initialized()
        # 每步用独立作用域: 写入立即提交, 下载期间不占着写事务 (BEGIN IMMEDIATE)
        async with self.db.session_scope(style="sqlalchemy") as session:
            # 上次进程中途退出会留下 DOWNLOADING, 这种行不在待下载列表里, 只能靠回收放回
            # FAILED 等重试。回收必须每轮做: 只在启动时做一次的话, 崩溃后很快重启
            # (间隔小于 request_timeout) 的那一行不会被回收, 之后再也没人看它。
            if n := await reclaim_stale_downloading(
                session, older_than=timedelta(seconds=self.request_timeout)
            ):
                logger.warning(f"回收了 {n} 个中断的媒体下载")
            sources = await list_pending_media_sources(session, limit=self.batch_size)
        if sources:
            logger.debug(f"媒体下载 worker 获取到 {len(sources)} 个待处理来源")
        for source in sources:
            source_id = source.id
            async with self.db.session_scope(style="sqlalchemy") as session:
                await mark_media_source_downloading(session, source_id)
            logger.debug(
                f"开始下载媒体: source_id={source_id} "
                f"type={source.media_type} file_id={source.source_file_id}"
            )
            try:
                payload = await download_media_source(
                    http_session,
                    source,
                    root=self.cache_root,
                    data_root=self.data_root,
                    max_bytes=self.max_bytes,
                )
            except Exception as exc:  # noqa: BLE001 - 任何下载失败都要落库重试, 不能打断 worker
                permanent = is_permanent_failure(exc)
                async with self.db.session_scope(style="sqlalchemy") as session:
                    await mark_media_source_failed(
                        session,
                        source_id,
                        repr(exc),
                        max_attempts=self.max_attempts,
                        retry_base=self.retry_base,
                        retry_cap=self.retry_cap,
                        permanent=permanent,
                    )
                # 链接过期是常态, 不刷 warning
                log = logger.info if permanent else logger.warning
                log(
                    f"媒体下载失败{'(不再重试)' if permanent else ''}: "
                    f"source_id={source_id} type={source.media_type} error={exc!r}"
                )
                continue
            async with self.db.session_scope(style="sqlalchemy") as session:
                await mark_media_source_downloaded(session, source_id, payload)
            logger.info(
                f"媒体下载完成: source_id={source_id} type={source.media_type} "
                f"size={payload.size} sha256={payload.sha256} path={payload.cache_path}"
            )
