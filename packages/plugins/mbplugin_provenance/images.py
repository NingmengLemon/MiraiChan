"""从 OneBot 消息里取图片: 回复目标、图片段、本地路径与 media type。

这些都不依赖 melobot 的 bot 实例, 单测可以直接调。
"""

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import aiohttp
from lemony_network.request import (
    HTTP_HEADERS,
    ResponseTooLargeError,
    download_bytes,
)
from lemony_storage_helper.files import (
    get_data_root,
    is_data_root_set,
    mime_from_content,
    safe_suffix,
)

from .client import ProvenanceError

__all__ = [
    "download_image",
    "image_payloads",
    "local_candidates",
    "mime_of",
    "segment_dict",
]

logger = logging.getLogger(__name__)

_SUFFIX_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def segment_dict(segment: object) -> Mapping[str, Any]:
    """把 get_msg 返回的段统一成 {"type": ..., "data": {...}} 形态"""
    if isinstance(segment, Mapping):
        return segment
    raw = getattr(segment, "raw", None)
    if isinstance(raw, Mapping):
        return raw
    to_dict = getattr(segment, "to_dict", None)
    if to_dict is not None:
        return to_dict()
    return {}


def image_payloads(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """消息体里所有 image 段的 data"""
    images: list[Mapping[str, Any]] = []
    for segment in payload.get("message") or []:
        data = segment_dict(segment)
        if data.get("type") == "image":
            seg_data = data.get("data")
            if isinstance(seg_data, Mapping):
                images.append(seg_data)
    return images


def _under_roots(path: Path, roots: Sequence[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        return True
    return False


def local_candidates(
    seg_data: Mapping[str, Any], allowed_dirs: Sequence[str | Path] = ()
) -> list[Path]:
    """图片段里可能的本地路径, 只接受 data root 或显式允许目录内的文件.

    ``file`` 可能是绝对路径, 也可能相对 data root. 绝对路径不会无条件信任:
    实现端把图片放在 data root 之外时, 需要在配置 ``image_dirs`` 里显式列出允许目录.
    """
    raw = seg_data.get("file")
    if not isinstance(raw, str) or not raw or not is_data_root_set():
        return []
    data_root = get_data_root()
    roots = [data_root]
    for allowed in allowed_dirs:
        root = Path(allowed)
        if not root.is_absolute():
            root = data_root / root
        roots.append(root)

    if raw.startswith("file://"):
        parts = urlparse(raw)
        # Windows 上 file://C:/x 的盘符会落进 netloc
        if parts.netloc and parts.netloc != "localhost":
            path = Path(unquote(parts.netloc + parts.path))
        else:
            path = Path(unquote(parts.path))
    else:
        path = Path(raw)
        if not path.is_absolute():
            path = data_root / path
    try:
        if not path.is_file() or not _under_roots(path, roots):
            logger.debug("拒绝读取 data root 外的本地图片: %s", raw)
            return []
    except OSError:
        return []
    return [path]


def mime_of(data: bytes, seg_data: Mapping[str, Any], url: str | None) -> str:
    """文件 part 的 media type: 优先按魔数, 其次按后缀"""
    mime = mime_from_content(data)
    if mime:
        return mime
    suffix = safe_suffix(url) or safe_suffix(seg_data.get("file"))
    return _SUFFIX_MIME.get(suffix, "application/octet-stream")


async def download_image(
    session: aiohttp.ClientSession,
    url: str,
    *,
    total_timeout: float,
    max_bytes: int,
) -> bytes:
    """下载一张图片; 超时、网络错误与超限都转成 ``ProvenanceError``."""
    try:
        return await download_bytes(
            session,
            url,
            max_bytes=max_bytes,
            total_timeout=total_timeout,
            headers=HTTP_HEADERS,
        )
    except ResponseTooLargeError as exc:
        raise ProvenanceError("图片太大了") from exc
    except (TimeoutError, aiohttp.ClientError) as exc:
        raise ProvenanceError("图片下载超时或失败") from exc
