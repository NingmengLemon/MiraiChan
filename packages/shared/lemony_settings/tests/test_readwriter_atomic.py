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
