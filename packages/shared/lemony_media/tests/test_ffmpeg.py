"""ffmpeg 封装的失败语义与超时参数."""

from __future__ import annotations

import logging
import subprocess
from typing import Any

import pytest
from lemony_media.ffmpeg import call_ffmpeg


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["ffmpeg"], returncode, "", stderr)


def test_call_ffmpeg_passes_timeout_and_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(cmd=cmd, kwargs=kwargs)
        return _completed(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert call_ffmpeg("-i", "in.flac", "out.mp3", timeout=12) == 0
    assert seen["kwargs"]["timeout"] == 12
    assert seen["cmd"][:4] == ["ffmpeg", "-y", "-loglevel", "error"]
    assert "-nostdin" in seen["cmd"]


def test_call_ffmpeg_logs_stderr_and_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *_args, **_kwargs: _completed(2, "bad input")
    )
    with caplog.at_level(logging.ERROR), pytest.raises(subprocess.CalledProcessError):
        call_ffmpeg("-i", "broken.flac", "out.mp3")
    assert "bad input" in caplog.text


def test_call_ffmpeg_check_false_returns_the_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *_args, **_kwargs: _completed(2, "bad input")
    )
    assert call_ffmpeg("-i", "broken.flac", "out.mp3", check=False) == 2
