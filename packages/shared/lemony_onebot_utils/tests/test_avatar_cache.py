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


def test_cache_dir_follows_data_root(tmp_path: Path) -> None:
    from lemony_storage_helper.files import set_data_root

    set_data_root(tmp_path)
    try:
        assert botutils.cached_avatar_source.cache_dir() == (
            tmp_path.resolve() / "avatars"
        )
    finally:
        set_data_root(None)


def test_freshness_uses_mtime_and_survives_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """新鲜度看文件 mtime: 重启后已有的新鲜文件直接命中, 过期的重新下载并原子写回"""
    import asyncio
    import os
    import time

    # AvatarCache 被 @singleton 包成了工厂函数, 补丁要打在共享实例上
    cache = botutils.cached_avatar_source
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache, "_auto_close", False)
    calls: list[int] = []

    async def fake_remote(uid: int) -> bytes:
        calls.append(uid)
        return b"new"

    monkeypatch.setattr(cache, "get_from_remote", fake_remote)
    (tmp_path / "1.png").write_bytes(b"cached")
    stale = tmp_path / "2.png"
    stale.write_bytes(b"old")
    old = time.time() - cache.EXPIRES - 60
    os.utime(stale, (old, old))

    assert asyncio.run(cache.get(1)) == b"cached"
    assert asyncio.run(cache.get(2)) == b"new"
    assert calls == [2]
    assert stale.read_bytes() == b"new"
    # 原子写入不留临时文件
    assert sorted(p.name for p in tmp_path.iterdir()) == ["1.png", "2.png"]
