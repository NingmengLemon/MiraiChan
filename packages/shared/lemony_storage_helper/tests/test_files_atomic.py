"""原子写入的测试。"""

import contextlib
import os
import threading
from pathlib import Path

import pytest
from lemony_storage_helper.files import atomic_write_bytes, atomic_write_text


def test_writes_new_file_and_returns_path(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "a.bin"
    assert atomic_write_bytes(target, b"hello") == target
    assert target.read_bytes() == b"hello"


def test_creates_missing_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c" / "x.bin"
    atomic_write_bytes(target, b"x")
    assert target.read_bytes() == b"x"


def test_replaces_existing_content(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_bytes(b"old content")
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"


def test_leaves_no_tmp_file(tmp_path: Path) -> None:
    atomic_write_bytes(tmp_path / "a.bin", b"x")
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]


def test_empty_payload(tmp_path: Path) -> None:
    target = tmp_path / "empty.bin"
    atomic_write_bytes(target, b"")
    assert target.read_bytes() == b""


def test_text_roundtrip_and_encoding(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    atomic_write_text(target, "中文 ok")
    assert target.read_text(encoding="utf-8") == "中文 ok"
    atomic_write_text(tmp_path / "b.txt", "gbk 内容", encoding="gbk")
    assert (tmp_path / "b.txt").read_bytes() == "gbk 内容".encode("gbk")


def test_failed_replace_keeps_old_file_and_cleans_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"keep me")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"keep me"
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]


def test_failed_flush_keeps_old_file_and_cleans_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """写临时文件的过程中失败 (例如磁盘满) 不能动到原文件"""

    def boom(fd):
        raise OSError("disk full")

    target = tmp_path / "a.bin"
    target.write_bytes(b"keep me")
    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"keep me"
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]


def test_fsync_flag_controls_the_sync_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))

    atomic_write_bytes(tmp_path / "a.bin", b"x")
    assert len(calls) == 1

    calls.clear()
    atomic_write_bytes(tmp_path / "b.bin", b"x", fsync=False)
    assert calls == []


def test_few_concurrent_writers_all_succeed(tmp_path: Path) -> None:
    """插件里的实际并发度 (写同一个缓存文件的没几个) 不该报错"""
    target = tmp_path / "a.bin"
    payloads = [bytes([i]) * (1024 * (i + 1)) for i in range(4)]
    errors: list[BaseException] = []

    def work(data: bytes) -> None:
        for _ in range(4):
            try:
                atomic_write_bytes(target, data)
            except BaseException as e:  # noqa: BLE001 - 收集起来在主线程断言
                errors.append(e)

    threads = [
        threading.Thread(target=work, args=(payload,)) for payload in payloads[:2]
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert target.read_bytes() in payloads
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]


def test_heavy_contention_never_leaves_a_partial_file(tmp_path: Path) -> None:
    """同一路径被大量线程争抢时个别写入可能仍失败 (Windows 共享冲突),

    但落盘的内容一定是某一次写入的完整结果, 也不会留下临时文件。
    """
    target = tmp_path / "a.bin"
    payloads = [bytes([i]) * (1024 * (i + 1)) for i in range(8)]

    def work(data: bytes) -> None:
        # 高并发下 Windows 的 replace 可能仍然撞共享冲突, 那不算这条测试关心的失败
        with contextlib.suppress(PermissionError):
            atomic_write_bytes(target, data)

    threads = [
        threading.Thread(target=work, args=(payload,)) for payload in payloads * 2
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert target.read_bytes() in payloads
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]
