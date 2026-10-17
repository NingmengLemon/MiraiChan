"""文件名清洗、内容寻址命名与可覆盖资源解析。"""

import os
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from lemony_storage_helper.files import (
    content_path,
    data_path,
    is_data_root_set,
    mime_from_content,
    resource_path,
    safe_suffix,
    set_data_root,
    suffix_from_content,
)


def _png_header() -> bytes:
    """一个足够让 puremagic 认出 png 的最小文件头"""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        + struct.pack(
            ">I", zlib.crc32(b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        )
    )


@pytest.fixture(autouse=True)
def _reset_root() -> Iterator[None]:
    yield
    set_data_root(None)


def test_safe_suffix_takes_the_last_part_of_urls_and_filenames() -> None:
    assert safe_suffix(".PNG") == ".png"
    assert safe_suffix("png") == ""
    assert safe_suffix("https://x/a/b.JPEG?token=1#frag") == ".jpeg"
    assert safe_suffix(r"C:\tmp\a\b.webp") == ".webp"
    assert safe_suffix("a.tar.gz") == ".gz"
    assert safe_suffix("no_suffix") == ""


def test_safe_suffix_rejects_executables_and_odd_shapes() -> None:
    for value in (
        None,
        "",
        ".exe",
        ".SH",
        "x.dll",
        "a.bat?x=1",
        ".longsuffixname",
        ".a.b",
    ):
        assert safe_suffix(value) == "", value


def test_suffix_and_mime_from_content() -> None:
    png = _png_header()
    assert suffix_from_content(png) == ".png"
    assert mime_from_content(png) == "image/png"
    assert suffix_from_content(b"not a known format at all") == ""
    assert mime_from_content(b"not a known format at all") is None
    # 空输入抛的是 PureValueError 而不是 PureError, 同样要当成"认不出来"
    assert suffix_from_content(b"") == ""
    assert mime_from_content(b"") is None


def test_suffix_from_content_drops_executable_magic() -> None:
    # MZ 头是 PE 可执行文件, 即使魔数认出来了也不能留后缀
    assert suffix_from_content(b"MZ\x90\x00" + b"\x00" * 64) == ""


def test_content_path_requires_a_sha256_digest(tmp_path: Path) -> None:
    digest = "a" * 64
    assert content_path(tmp_path, digest, suffix=".PNG") == tmp_path / f"{digest}.png"
    assert content_path(tmp_path, digest.upper()) == tmp_path / digest
    for bad in ("", "abc", "g" * 64, "a" * 63, "a" * 65):
        with pytest.raises(ValueError):
            content_path(tmp_path, bad)


def test_resource_path_prefers_the_override(tmp_path: Path) -> None:
    bundled = tmp_path / "pkg" / "resources"
    bundled.mkdir(parents=True)
    (bundled / "mask.png").write_bytes(b"bundled")
    override_root = tmp_path / "user"
    (override_root / "quote").mkdir(parents=True)
    (override_root / "quote" / "mask.png").write_bytes(b"user")

    assert (
        resource_path(
            bundled, "mask.png", identifier="quote", override_root=override_root
        )
        == override_root / "quote" / "mask.png"
    )
    # 用户没放同名文件时回落到包内资源
    assert (
        resource_path(
            bundled, "other.png", identifier="quote", override_root=override_root
        )
        == bundled / "other.png"
    )


def test_resource_path_uses_the_data_root_by_default(tmp_path: Path) -> None:
    set_data_root(tmp_path)
    bundled = tmp_path / "bundled"
    target = data_path("resources", "quote", "mask.png", mkdir_parent=True)
    target.write_bytes(b"user")

    assert resource_path(bundled, "mask.png", identifier="quote") == target


def test_resource_path_without_a_data_root_only_uses_the_bundled_copy(
    tmp_path: Path,
) -> None:
    set_data_root(None)
    assert not is_data_root_set()
    bundled = tmp_path / "bundled"
    assert (
        resource_path(bundled, "mask.png", identifier="quote") == bundled / "mask.png"
    )


def test_resource_path_allows_a_symlinked_override(tmp_path: Path) -> None:
    """覆盖目录里的符号链接指到别处是正常用法, 不该被当成越界"""

    external = tmp_path / "shared" / "real_mask.png"
    external.parent.mkdir()
    external.write_bytes(b"user")
    override_root = tmp_path / "user"
    (override_root / "quote").mkdir(parents=True)
    link = override_root / "quote" / "mask.png"
    try:
        os.symlink(external, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    assert (
        resource_path(
            tmp_path / "bundled",
            "mask.png",
            identifier="quote",
            override_root=override_root,
        )
        == link
    )


def test_resource_path_rejects_escapes(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resource_path(tmp_path, "../secret.png", identifier="quote")
    with pytest.raises(ValueError):
        resource_path(tmp_path, Path("a") / ".." / ".." / "x", identifier="quote")
    with pytest.raises(ValueError):
        resource_path(tmp_path, "x.png", identifier="../quote")
    with pytest.raises(ValueError):
        resource_path(tmp_path, "x.png", identifier="")
