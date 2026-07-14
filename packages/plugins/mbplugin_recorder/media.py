from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import aiofiles
import puremagic
from aiohttp import ClientSession
from lemony_network.request import http_headers

from .db.dto import MediaSourceInput
from .db.enums import MediaDownloadStatus
from .db.models import MediaSource

_UNTRUSTED_SUFFIXES = {
    ".suf",
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".vbs",
    ".js",
    ".msi",
    ".scr",
    ".com",
}
DEFAULT_MAX_MEDIA_BYTES = 512 * 1024 * 1024
_READ_CHUNK_SIZE = 1024 * 1024
_MAGIC_BYTES_LIMIT = 4096


def _filename_part(value: str) -> str:
    return value.split("?", 1)[0].rsplit("/", 1)[-1]


def _safe_suffix(value: str | None) -> str:
    if not value:
        return ""
    suffix = (
        value.lower()
        if value.startswith(".")
        else Path(_filename_part(value)).suffix.lower()
    )
    if suffix in _UNTRUSTED_SUFFIXES:
        return ""
    if not suffix:
        return ""
    suffix_body = suffix[1:]
    if not suffix_body or not suffix_body.isalnum():
        return ""
    return suffix


def _suffix_from_content(data: bytes) -> str:
    try:
        return _safe_suffix(puremagic.from_string(data))
    except puremagic.PureError:
        return ""


def _mime_from_content(data: bytes) -> str | None:
    try:
        mime_type = puremagic.from_string(data, mime=True)
    except puremagic.PureError:
        return None
    return mime_type or None


def media_cache_path(
    root: str | Path,
    source: MediaSource,
    *,
    sha256_hex: str | None = None,
    suffix: str | None = None,
) -> Path:
    file_stem = sha256_hex or source.source_file_id
    safe_file_stem = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in file_stem
    )
    safe_suffix = (
        _safe_suffix(suffix)
        or _safe_suffix(source.source_file_id)
        or _safe_suffix(source.url)
    )
    return Path(root) / source.media_type / f"{safe_file_stem or 'media'}{safe_suffix}"


async def download_media_source(
    http_session: ClientSession,
    source: MediaSource,
    *,
    root: str | Path,
    max_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
) -> MediaSourceInput:
    if not source.url:
        raise ValueError("media source has no url")

    media_root = Path(root) / source.media_type
    media_root.mkdir(parents=True, exist_ok=True)
    tmp_path = media_root / f"{uuid4().hex}.download"
    digest = sha256()
    size = 0
    magic_data = bytearray()

    try:
        async with http_session.get(source.url, headers=http_headers) as response:
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
        suffix = _suffix_from_content(bytes(magic_data)) or _safe_suffix(source.url)
        mime_type = _mime_from_content(bytes(magic_data))
        target_path = media_cache_path(
            root, source, sha256_hex=sha256_hex, suffix=suffix
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.replace(target_path)
    except Exception:
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
        cache_path=target_path.as_posix(),
    )
