"""ColorFontEmoji 的测试.

彩色字体不在仓库里, 所以字体相关的行为用两样东西验证:
Pillow 自带字体验证通用路径, 以及手工拼出来的 sfnt 验证位图字体的字号选择。
"""

import logging
import struct
from io import BytesIO
from pathlib import Path

import pytest
from lemony_images.text import ColorFontEmoji
from PIL import Image, ImageFont


def _write_default_font(path: Path) -> Path:
    """Pillow 自带的字体是打包在二进制里的, 取出来落到文件才能按路径打开"""
    font = ImageFont.load_default(28)
    assert isinstance(font, ImageFont.FreeTypeFont)
    embedded = font.path
    if isinstance(embedded, BytesIO):
        path.write_bytes(embedded.getvalue())
        return path
    assert isinstance(embedded, str)
    return Path(embedded)


@pytest.fixture
def monochrome_font(tmp_path: Path) -> Path:
    return _write_default_font(tmp_path / "default.otf")


def _fake_bitmap_font(path: Path, strikes: list[int]) -> Path:
    """拼一个只含 CBDT/CBLC 表头的字体, 用来验证字号选择"""
    cblc = struct.pack(">II", 0x00030000, len(strikes))
    for ppem in strikes:
        record = bytearray(48)
        record[44] = ppem
        record[45] = ppem
        cblc += bytes(record)
    header = struct.pack(">IHHHH", 0x00010000, 2, 0, 0, 0)
    cblc_offset = 12 + 16 * 2
    records = b"".join(
        tag + struct.pack(">III", 0, offset, length)
        for tag, offset, length in (
            (b"CBDT", cblc_offset + len(cblc), 0),
            (b"CBLC", cblc_offset, len(cblc)),
        )
    )
    path.write_bytes(header + records + cblc)
    return path


def _fake_colr_font(path: Path, version: int) -> Path:
    """拼一个只含 COLR 表头的字体, 用来验证彩色表版本判断"""
    colr = struct.pack(">HH", version, 0)
    header = struct.pack(">IHHHH", 0x00010000, 1, 0, 0, 0)
    offset = 12 + 16
    path.write_bytes(
        header + b"COLR" + struct.pack(">III", 0, offset, len(colr)) + colr
    )
    return path


def _fake_svg_font(path: Path) -> Path:
    """拼一个只含 SVG 表头的字体, 用来验证表名尾随空格不会漏判"""
    svg = b"\x00\x00"
    header = struct.pack(">IHHHH", 0x00010000, 1, 0, 0, 0)
    offset = 12 + 16
    path.write_bytes(header + b"SVG " + struct.pack(">III", 0, offset, len(svg)) + svg)
    return path


def test_monochrome_font_is_not_color(monochrome_font: Path) -> None:
    renderer = ColorFontEmoji(monochrome_font)
    assert renderer.is_color is False


def test_render_returns_ink_without_transparent_border(monochrome_font: Path) -> None:
    renderer = ColorFontEmoji(monochrome_font)
    image = renderer.render("A", target=32)
    assert image is not None
    assert image.mode == "RGBA"
    assert max(image.size) <= 32
    # 裁掉透明边距之后四边都有墨迹
    assert image.getbbox() == (0, 0, image.width, image.height)


def test_render_returns_none_for_glyphless_input(monochrome_font: Path) -> None:
    renderer = ColorFontEmoji(monochrome_font)
    assert renderer.render(" ", target=32) is None


def test_missing_glyph_returns_none_not_a_tofu_box(monochrome_font: Path) -> None:
    """字体里没有的字形画出来是 .notdef, 要当成"没有"而不是一张图

    否则"字体里没有就走下一级来源"的兜底永远触发不了, 用户会看到黑框。
    """
    renderer = ColorFontEmoji(monochrome_font)
    assert renderer.render("\U0001fae0", target=32) is None
    assert renderer.render("\ufdd0", target=32) is None


def test_known_glyph_still_renders(monochrome_font: Path) -> None:
    """修掉 .notdef 误判之后, 真的字形不能跟着一起变成 None"""
    renderer = ColorFontEmoji(monochrome_font)
    assert renderer.render("A", target=32) is not None


def test_wide_cluster_is_not_clipped(monochrome_font: Path) -> None:
    """画布按簇的实际 advance 定宽, 宽簇不能被切掉

    未成合字的 ZWJ 序列 (旧字体常见) 会占好几个字号的宽度。
    """
    renderer = ColorFontEmoji(monochrome_font)
    size = 40
    text = "WO" * 8  # 一串宽字, 足够超出"两倍字号"宽
    image = renderer._paint(text, size)
    font = ImageFont.truetype(str(monochrome_font), size)
    advance = font.getlength(text)
    pad = max(4, size // 3)
    assert image is not None
    # 老实现只给 2*字号 + 2*pad 的画布, 这里必须比那个宽
    assert image.width > 2 * size + 2 * pad
    # 宽度跟着实际 advance 走 (取整与字距调整留几像素余量)
    assert abs(image.width - advance) <= 4


def test_render_caches_by_cluster_and_target(monochrome_font: Path) -> None:
    renderer = ColorFontEmoji(monochrome_font)
    first = renderer.render("A", target=32)
    assert renderer.render("A", target=32) is first
    assert renderer.render("A", target=64) is not first
    renderer.clear()
    assert renderer.render("A", target=32) is not first


@pytest.mark.parametrize(
    ("strikes", "want", "expected"),
    [
        ([109], 160, 109),
        ([109], 28, 109),
        ([109], 109, 109),
        ([64, 109], 28, 64),
        ([64, 109], 100, 109),
    ],
)
def test_bitmap_font_uses_its_own_strike(
    tmp_path: Path, strikes: list[int], want: int, expected: int
) -> None:
    path = _fake_bitmap_font(tmp_path / "fake.ttf", strikes)
    renderer = ColorFontEmoji(path)
    assert renderer.is_color is True
    assert renderer._render_size(want) == expected


def test_missing_font_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        ColorFontEmoji(tmp_path / "nope.ttf")


def test_bitmap_font_can_rasterize_color(tmp_path: Path) -> None:
    renderer = ColorFontEmoji(_fake_bitmap_font(tmp_path / "bitmap.ttf", [109]))
    assert renderer.is_color is True
    assert renderer.can_rasterize_color is True


def test_colr_v0_font_can_rasterize_color(tmp_path: Path) -> None:
    renderer = ColorFontEmoji(_fake_colr_font(tmp_path / "v0.ttf", 0))
    assert renderer.colr_version == 0
    assert renderer.can_rasterize_color is True


def test_colr_v1_font_cannot_rasterize_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _fake_colr_font(tmp_path / "v1.ttf", 1)
    with caplog.at_level(logging.WARNING, logger="lemony_images.text.emoji"):
        renderer = ColorFontEmoji(path)
    assert renderer.is_color is True
    assert renderer.colr_version == 1
    assert renderer.can_rasterize_color is False
    assert "COLRv1" in caplog.text


def test_svg_table_counts_as_color_but_not_rasterizable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _fake_svg_font(tmp_path / "svg.ttf")
    with caplog.at_level(logging.WARNING, logger="lemony_images.text.emoji"):
        renderer = ColorFontEmoji(path)
    assert renderer.is_color is True
    assert renderer.can_rasterize_color is False
    assert "Pillow 画不出" in caplog.text


def test_rendered_image_fits_target(monochrome_font: Path) -> None:
    renderer = ColorFontEmoji(monochrome_font)
    image = renderer.render("W", target=16)
    assert image is not None
    assert isinstance(image, Image.Image)
    assert max(image.size) <= 16
