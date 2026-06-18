from __future__ import annotations

from enum import StrEnum


class MediaDownloadStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
