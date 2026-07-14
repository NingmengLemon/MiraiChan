import asyncio
from contextlib import suppress

from aiohttp import ClientSession
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from melobot import get_logger

from .db.operations import (
    list_pending_media_sources,
    mark_media_source_downloaded,
    mark_media_source_downloading,
    mark_media_source_failed,
)
from .media import DEFAULT_MAX_MEDIA_BYTES, download_media_source

logger = get_logger()


class MediaDownloadWorker:
    def __init__(
        self,
        db: SqliteDatabaseHelper,
        *,
        cache_root: str = "record/media",
        interval: float = 10.0,
        batch_size: int = 10,
        max_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
    ) -> None:
        self.db = db
        self.cache_root = cache_root
        self.interval = interval
        self.batch_size = batch_size
        self.max_bytes = max_bytes
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run())
            logger.info(
                f"媒体下载 worker 已启动: root={self.cache_root}, "
                f"interval={self.interval}, batch_size={self.batch_size}, "
                f"max_bytes={self.max_bytes}"
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
        async with ClientSession() as http_session:
            while not self._stop_event.is_set():
                try:
                    await self.run_once(http_session)
                except Exception:
                    logger.generic_exc("媒体下载 worker 执行失败")
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.interval
                    )

    async def run_once(self, http_session: ClientSession) -> None:
        await self.db.wait_until_initialized()
        async with self.db.get_session(style="sqlalchemy") as session:
            sources = await list_pending_media_sources(session, limit=self.batch_size)
            if sources:
                logger.debug(f"媒体下载 worker 获取到 {len(sources)} 个待处理来源")
            for source in sources:
                await mark_media_source_downloading(session, source.id)
                logger.debug(
                    f"开始下载媒体: source_id={source.id} "
                    f"type={source.media_type} file_id={source.source_file_id}"
                )
                try:
                    payload = await download_media_source(
                        http_session,
                        source,
                        root=self.cache_root,
                        max_bytes=self.max_bytes,
                    )
                except Exception as exc:
                    await mark_media_source_failed(session, source.id, repr(exc))
                    logger.warning(
                        f"媒体下载失败: source_id={source.id} "
                        f"type={source.media_type} file_id={source.source_file_id} "
                        f"error={exc!r}"
                    )
                    continue
                await mark_media_source_downloaded(session, source.id, payload)
                logger.info(
                    f"媒体下载完成: source_id={source.id} type={source.media_type} "
                    f"size={payload.size} sha256={payload.sha256} "
                    f"path={payload.cache_path}"
                )
