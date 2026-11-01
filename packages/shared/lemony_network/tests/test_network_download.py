"""共享下载工具的单元测试 (不联网)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from lemony_network import ResponseTooLargeError, download_bytes


class _Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class _Response:
    def __init__(self, chunks: list[bytes], content_length: int | None = None) -> None:
        self.content = _Content(chunks)
        self.content_length = content_length

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response

    def request(self, *_args: Any, **_kwargs: Any) -> _Response:
        return self._response


class _CaptureSession:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def request(self, *_args: Any, **kwargs: Any) -> _Response:
        self.kwargs = kwargs
        return _Response([b"x"])


@pytest.mark.asyncio
async def test_download_bytes_returns_all_chunks() -> None:
    session = _Session(_Response([b"abc", b"def"], content_length=6))
    assert (
        await download_bytes(
            cast(Any, session), "https://example.invalid/x", max_bytes=10
        )
        == b"abcdef"
    )


@pytest.mark.asyncio
async def test_download_bytes_rejects_declared_size() -> None:
    session = _Session(_Response([b"abc"], content_length=11))
    with pytest.raises(ResponseTooLargeError, match="exceeds max size"):
        await download_bytes(
            cast(Any, session), "https://example.invalid/x", max_bytes=10
        )


@pytest.mark.asyncio
async def test_download_bytes_rejects_streamed_size() -> None:
    session = _Session(_Response([b"a" * 6, b"b" * 6]))
    with pytest.raises(ResponseTooLargeError, match="exceeds max size"):
        await download_bytes(
            cast(Any, session), "https://example.invalid/x", max_bytes=10
        )


@pytest.mark.asyncio
async def test_qqnt_tls_only_for_the_exact_hostname() -> None:
    exact = _CaptureSession()
    await download_bytes(
        cast(Any, exact), "https://multimedia.nt.qq.com.cn/x", max_bytes=10
    )
    assert exact.kwargs["ssl"] is not True

    spoofed = _CaptureSession()
    await download_bytes(
        cast(Any, spoofed),
        "https://evil.example/multimedia.nt.qq.com.cn/x",
        max_bytes=10,
    )
    assert spoofed.kwargs["ssl"] is True
