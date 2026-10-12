"""lemony_onebot_utils 单元测试 —— 头像缓存的 session 超时.

回归点: get_from_remote 带 3 次重试, 而 session 以前是裸 ``ClientSession()``
(aiohttp 默认 total 300s)。一个连不上的头像地址会让调用方 (签到、引用渲染) 等上
十几分钟, 期间既不出图也不报错。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import ClientTimeout
from lemony_onebot_utils import botutils
from lemony_onebot_utils.botutils import AVATAR_REQUEST_TIMEOUT, AvatarCache


def test_avatar_request_timeout_is_bounded():
    assert 0 < AVATAR_REQUEST_TIMEOUT <= 60


def test_session_is_created_with_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """共享 session 必须显式带上超时, 否则等于用 aiohttp 的默认 300s。"""
    recorded: dict[str, object] = {}

    class RecordingSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            recorded.update(kwargs)

    monkeypatch.setattr(botutils, "ClientSession", RecordingSession)
    monkeypatch.setattr(AvatarCache, "CACHE_DIR", str(tmp_path))
    cache = AvatarCache(auto_close=False)
    monkeypatch.setattr(cache, "_session", None)

    cache._ensure_session()

    timeout = recorded.get("timeout")
    assert isinstance(timeout, ClientTimeout)
    assert timeout.total == AVATAR_REQUEST_TIMEOUT


def test_existing_session_is_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(AvatarCache, "CACHE_DIR", str(tmp_path))
    cache = AvatarCache(auto_close=False)
    sentinel = object()
    monkeypatch.setattr(cache, "_session", sentinel)

    assert cache._ensure_session() is sentinel
