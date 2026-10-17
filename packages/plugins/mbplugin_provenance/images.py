"""从 OneBot 消息里取图片: 回复目标、图片段、本地路径与 media type。

这些都不依赖 melobot 的 bot 实例, 单测可以直接调。
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from lemony_storage_helper.files import (
    get_data_root,
    is_data_root_set,
    mime_from_content,
    safe_suffix,
)

__all__ = ["image_payloads", "local_candidates", "mime_of", "segment_dict"]

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


def local_candidates(seg_data: Mapping[str, Any]) -> list[Path]:
    """图片段里可能的本地路径: file 可能是绝对路径, 也可能相对 data root"""
    raw = seg_data.get("file")
    if not isinstance(raw, str) or not raw or not is_data_root_set():
        return []
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
            path = get_data_root() / path
    try:
        return [path] if path.is_file() else []
    except OSError:
        return []


def mime_of(data: bytes, seg_data: Mapping[str, Any], url: str | None) -> str:
    """文件 part 的 media type: 优先按魔数, 其次按后缀"""
    mime = mime_from_content(data)
    if mime:
        return mime
    suffix = safe_suffix(url) or safe_suffix(seg_data.get("file"))
    return _SUFFIX_MIME.get(suffix, "application/octet-stream")
