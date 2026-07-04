import asyncio
from collections.abc import Callable
from functools import partial
from logging import LogRecord

from melobot._run import create_immunity_task, is_runner_running
from melobot.log.handler import (
    FastRotatingFileHandler,
    FastStreamHandler,
    _format_cb,
)


def _has_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _emit_with_thread_fallback(
    record: LogRecord,
    async_emit: Callable[[LogRecord], None],
    sync_emit: Callable[[LogRecord], None],
) -> None:
    if is_runner_running() and _has_running_loop():
        async_emit(record)
    else:
        sync_emit(record)


def _fast_stream_emit(self: FastStreamHandler, record: LogRecord) -> None:
    def async_emit(record: LogRecord) -> None:
        task = create_immunity_task(self.render.async_format(record))
        task.add_done_callback(
            partial(_format_cb, record, super(FastStreamHandler, self).emit)
        )

    def sync_emit(record: LogRecord) -> None:
        self.render.sync_format(record)
        super(FastStreamHandler, self).emit(record)

    _emit_with_thread_fallback(record, async_emit, sync_emit)


def _fast_rotating_file_emit(self: FastRotatingFileHandler, record: LogRecord) -> None:
    def async_emit(record: LogRecord) -> None:
        task = create_immunity_task(self.render.async_format(record))
        task.add_done_callback(
            partial(_format_cb, record, super(FastRotatingFileHandler, self).emit)
        )

    def sync_emit(record: LogRecord) -> None:
        self.render.sync_format(record)
        super(FastRotatingFileHandler, self).emit(record)

    _emit_with_thread_fallback(record, async_emit, sync_emit)


def patch_melobot_thread_logging() -> None:
    """Patch melobot log handlers to be safe when logging from worker threads.

    melobot's fast handlers choose async rendering based on its global runner state.
    When log calls happen inside `asyncio.to_thread()`, the runner is active but the
    worker thread has no running event loop, so `asyncio.create_task()` raises
    `RuntimeError: no running event loop`.  Keep melobot's async path for normal
    event-loop-thread logging and fall back to sync formatting only for threads
    without a running event loop.
    """

    FastStreamHandler.emit = _fast_stream_emit  # type: ignore[method-assign]
    FastRotatingFileHandler.emit = _fast_rotating_file_emit  # type: ignore[method-assign]
