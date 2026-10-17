"""lemony_settings 配置写入的原子性.

回归点: 三个 writer 以前都直接截断写目标文件。写到一半崩溃 / 磁盘写满就会留下半个配置
文件, 下次加载解析失败, 而文件"存在"又不会重新生成默认配置, 于是只能人工修。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from lemony_settings.readwriter import (
    ConfigReadWriterABC,
    JsonReadWriter,
    TomlReadWriter,
    YamlReadWriter,
    get_readwriter,
)
from pydantic import BaseModel


class _Model(BaseModel):
    mode: str = "blacklist"
    count: int = 1


@pytest.mark.parametrize(
    ("fmt", "writer_cls"),
    [
        ("json", JsonReadWriter),
        ("yaml", YamlReadWriter),
        ("toml", TomlReadWriter),
    ],
)
def test_write_leaves_no_temp_file(
    fmt: str, writer_cls: type[ConfigReadWriterABC], tmp_path: Path
) -> None:
    path = tmp_path / f"cfg.{fmt}"
    writer_cls().write(path, _Model(mode="whitelist"))

    assert writer_cls().read(path, _Model) == _Model(mode="whitelist")
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.parametrize("fmt", ["json", "yaml", "toml"])
def test_failed_replace_keeps_the_old_file(
    fmt: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落盘失败 (如磁盘写满) 时目标文件必须还是上一次的完整内容."""
    path = tmp_path / f"cfg.{fmt}"
    writer = get_readwriter(fmt)
    writer.write(path, _Model(mode="whitelist"))
    before = path.read_bytes()

    def boom(src: Any, dst: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        writer.write(path, _Model(mode="blacklist"))

    assert path.read_bytes() == before
    assert list(tmp_path.glob(".*.tmp")) == []


def test_each_write_uses_its_own_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """固定的临时文件名会让同一目标的并发写入互相覆盖半成品."""
    path = tmp_path / "cfg.json"
    sources: list[str] = []
    real_replace = os.replace

    def spy(src: Any, dst: Any, **kwargs: Any) -> None:
        sources.append(str(src))
        real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", spy)
    writer = get_readwriter("json")
    writer.write(path, _Model(mode="whitelist"))
    writer.write(path, _Model(mode="blacklist"))

    assert len(set(sources)) == 2
    assert writer.read(path, _Model) == _Model(mode="blacklist")


@pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位")
def test_existing_file_mode_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "cfg.json"
    writer = get_readwriter("json")
    writer.write(path, _Model())
    path.chmod(0o640)
    writer.write(path, _Model(mode="whitelist"))
    assert path.stat().st_mode & 0o777 == 0o640
