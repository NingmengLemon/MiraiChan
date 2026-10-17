from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import aiofiles
from aiohttp import ClientSession
from lemony_network.request import HTTP_HEADERS
from lemony_storage_helper.files import (
    content_path,
    mime_from_content,
    safe_suffix,
    suffix_from_content,
)

from .db.dto import MediaSourceInput
from .db.enums import MediaDownloadStatus
from .db.models import MediaSource

DEFAULT_MAX_MEDIA_BYTES = 512 * 1024 * 1024
_READ_CHUNK_SIZE = 1024 * 1024
_MAGIC_BYTES_LIMIT = 4096


def _safe_file_stem(value: str) -> str:
    """没有内容摘要时用来源 id 当文件名: 只留字母数字和 - _"""
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)


def media_cache_path(
    root: str | Path,
    source: MediaSource,
    *,
    sha256_hex: str | None = None,
    suffix: str | None = None,
) -> Path:
    safe = (
        safe_suffix(suffix)
        or safe_suffix(source.source_file_id)
        or safe_suffix(source.url)
    )
    if sha256_hex:
        return content_path(Path(root) / source.media_type, sha256_hex, suffix=safe)
    stem = _safe_file_stem(source.source_file_id) or "media"
    return Path(root) / source.media_type / f"{stem}{safe}"


async def download_media_source(
    http_session: ClientSession,
    source: MediaSource,
    *,
    root: str | Path,
    data_root: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
) -> MediaSourceInput:
    """下载到 ``data_root / root`` 下; 记录的 cache_path 是相对 data_root 的 ``root/...``。

    data_root 为 None 时 root 相对当前目录, cache_path 也原样记录。
    """
    if not source.url:
        raise ValueError("media source has no url")

    base = Path(data_root) if data_root is not None else Path()
    media_root = base / root / source.media_type
    media_root.mkdir(parents=True, exist_ok=True)
    tmp_path = media_root / f"{uuid4().hex}.download"
    digest = sha256()
    size = 0
    magic_data = bytearray()

    try:
        async with http_session.get(source.url, headers=HTTP_HEADERS) as response:
            response.raise_for_status()
            content_length = response.content_length
            if content_length is not None and content_length > max_bytes:
                raise ValueError(
                    f"media source exceeds max size: {content_length} > {max_bytes}"
                )
            async with aiofiles.open(tmp_path, "wb") as tmp_file:
                async for chunk in response.content.iter_chunked(_READ_CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(
                            f"media source exceeds max size: > {max_bytes}"
                        )
                    digest.update(chunk)
                    if len(magic_data) < _MAGIC_BYTES_LIMIT:
                        remaining = _MAGIC_BYTES_LIMIT - len(magic_data)
                        magic_data.extend(chunk[:remaining])
                    await tmp_file.write(chunk)

        sha256_hex = digest.hexdigest()
        suffix = suffix_from_content(bytes(magic_data)) or safe_suffix(source.url)
        mime_type = mime_from_content(bytes(magic_data))
        relative_path = media_cache_path(
            root, source, sha256_hex=sha256_hex, suffix=suffix
        )
        target_path = base / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.replace(target_path)
    except BaseException:
        # CancelledError 不是 Exception: 进程停止 (worker.stop 取消任务) 时下载会被取消,
        # 只捕 Exception 的话每次取消都会在媒体目录里留下一个 .download 半成品
        with suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise

    return MediaSourceInput(
        source_file_id=source.source_file_id,
        media_type=source.media_type,
        url=source.url,
        download_status=MediaDownloadStatus.DOWNLOADED,
        size=size,
        mime_type=mime_type,
        sha256=sha256_hex,
        cache_path=relative_path.as_posix(),
    )
