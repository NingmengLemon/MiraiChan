"""同步工具不能把目标根目录当成待清理目录."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.walk_compress_sync_audios import _convert, reversed_sync, straight_sync


def test_reversed_sync_refuses_missing_source(tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "x.mp3").write_bytes(b"x")

    with pytest.raises(ValueError, match="源目录不存在"):
        reversed_sync(str(tmp_path / "missing"), str(dst))

    assert (dst / "x.mp3").exists()


def test_reversed_sync_keeps_destination_root(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "x.mp3").write_bytes(b"x")

    stat = reversed_sync(str(src), str(dst))

    assert not (dst / "x.mp3").exists()
    assert dst.is_dir()
    assert stat.dfile == 1


def test_straight_sync_rejects_same_or_nested_roots(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()

    with pytest.raises(ValueError, match="不能相同"):
        next(straight_sync(str(src), str(src)))

    with pytest.raises(ValueError, match="不能互相包含"):
        next(straight_sync(str(src), str(src / "out")))


def test_convert_keeps_target_extension_for_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.flac"
    source.write_bytes(b"source")
    target = tmp_path / "out.mp3"
    seen: dict[str, str] = {}

    def fake_convert(source: str, output: str, **kwargs: object) -> int:
        seen["output"] = output
        Path(output).write_bytes(b"converted")
        return 0

    monkeypatch.setattr("tools.walk_compress_sync_audios.convert_audio", fake_convert)

    code, result = _convert(str(source), str(target), 1.0)

    assert code == 0
    assert result == str(target)
    assert seen["output"].endswith(".part.mp3")
    assert target.read_bytes() == b"converted"
