from __future__ import annotations

from enum import StrEnum


class MediaDownloadStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    """失败但还会重试"""
    ABANDONED = "abandoned"
    """重试次数用尽, 不再尝试"""
