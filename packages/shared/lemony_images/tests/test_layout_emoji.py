"""带 emoji 的排版与绘制。

真实彩色字体不在仓库里, 这里用 Pillow 自带字体加一个固定返回色块的渲染器,
验证的是"测量与绘制用同一套规则"以及贴图路径本身。
"""

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from lemony_images.emoji import ColorFontEmoji, draw_emoji_line, emoji_line_width
from lemony_images.font import FontCache
from lemony_images.layout import (
    calc_font_size,
    draw_multiline_text_auto,
    wrap_text_by_width,
)
from PIL import Image, ImageDraw, ImageFont

BLOCK = (255, 0, 0, 255)  # 用一个纯红方块代替字形
_WHITE = (255, 255, 255, 255)


def _write_default_font(path: Path) -> Path:
    """把 Pillow 自带字体落到文件, 才能按路径打开。

    只写一次: 字体文件被 FreeType 映射之后再截断同一条路径, Windows 会报 EINVAL。
    """
    if path.exists():
        return path
    font = ImageFont.load_default(20)
    assert isinstance(font, ImageFont.FreeTypeFont)
    embedded = font.path
    if isinstance(embedded, BytesIO):
        path.write_bytes(embedded.getvalue())
        return path
    assert isinstance(embedded, str)
    return Path(embedded)


class _StubRenderer(ColorFontEmoji):
    """固定返回同一张图片的渲染器"""

    icon: Image.Image

    def render(self, cluster: str, *, target: int = 160) -> Image.Image | None:
        return self.icon


def _red_mask(canvas: Image.Image) -> np.ndarray:
    arr = np.array(canvas.convert("RGBA"))
    return (
        (arr[:, :, 0] == 255)
        & (arr[:, :, 1] == 0)
        & (arr[:, :, 2] == 0)
        & (arr[:, :, 3] == 255)
    )


@pytest.fixture(scope="module")
def font_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write_default_font(tmp_path_factory.mktemp("font") / "default.otf")


@pytest.fixture
def font(font_file: Path) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_file), 20)


@pytest.fixture
def renderer(font_file: Path) -> _StubRenderer:
    stub = _StubRenderer(font_file)
    stub.icon = Image.new("RGBA", (20, 20), BLOCK)
    return stub


def test_emoji_cluster_takes_one_square(font: ImageFont.FreeTypeFont) -> None:
    assert emoji_line_width("⭐", font) == pytest.approx(font.size)
    # ZWJ 序列整体算一块, 不是每个码位一块
    assert emoji_line_width("👨‍👩‍👧‍👦", font) == pytest.approx(font.size)


def test_plain_text_uses_measured_width(font: ImageFont.FreeTypeFont) -> None:
    assert emoji_line_width("hello", font) == pytest.approx(font.getlength("hello"))
    mixed = emoji_line_width("a⭐b", font)
    assert mixed == pytest.approx(font.getlength("ab") + font.size)


def test_draw_emoji_line_reports_width_and_composites(
    font: ImageFont.FreeTypeFont, renderer: _StubRenderer
) -> None:
    canvas = Image.new("RGBA", (120, 40), _WHITE)
    width = draw_emoji_line(canvas, (4, 4), "a⭐b", font, renderer, (0, 0, 0, 255))
    assert width == pytest.approx(font.getlength("ab") + font.size)
    assert _red_mask(canvas).any()


def test_draw_multiline_text_auto_draws_emoji_when_renderer_given(
    font_file: Path, renderer: _StubRenderer
) -> None:
    canvas = Image.new("RGBA", (400, 120), _WHITE)
    draw_multiline_text_auto(
        (0, 0, 400, 120),
        ImageDraw.Draw(canvas),
        "emoji ⭐ here",
        FontCache(font_file=font_file),
        max_font_size=28,
        emoji_renderer=renderer,
    )
    assert _red_mask(canvas).any()


def test_draw_multiline_text_auto_without_renderer_has_no_block(
    font_file: Path,
) -> None:
    canvas = Image.new("RGBA", (400, 120), _WHITE)
    draw_multiline_text_auto(
        (0, 0, 400, 120),
        ImageDraw.Draw(canvas),
        "emoji ⭐ here",
        FontCache(font_file=font_file),
        max_font_size=28,
    )
    assert not _red_mask(canvas).any()


def test_right_alignment_lines_share_right_edge(
    font_file: Path, renderer: _StubRenderer
) -> None:
    """右对齐是行与行之间对齐, 宽度不同的两行右边缘应重合"""
    canvas = Image.new("RGBA", (200, 120), _WHITE)
    draw_multiline_text_auto(
        (0, 0, 200, 120),
        ImageDraw.Draw(canvas),
        "⭐\n⭐⭐",
        FontCache(font_file=font_file),
        max_font_size=20,
        min_font_size=20,
        align="right",
        spacing=8,
        emoji_renderer=renderer,
    )
    mask = _red_mask(canvas)
    rows = np.nonzero(mask.any(axis=1))[0]
    assert rows.size, "没有贴上色块"
    # 按行拆开, 两行各自的右边缘
    bands = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1)
    assert len(bands) == 2, f"期望两行, 实际 {len(bands)}"
    edges = [int(np.nonzero(mask[band].any(axis=0))[0].max()) for band in bands]
    assert edges[0] == edges[1]
    assert edges[0] < 200


def test_wrap_keeps_emoji_cluster_whole(font: ImageFont.FreeTypeFont) -> None:
    """按方块算宽度时, 一个簇占一格, 不能被拆到两行"""
    family = "👨‍👩‍👧‍👦"
    assert wrap_text_by_width(family, 25, font, emoji_as_square=True) == [family]
    # 逐字符断行 (不按方块) 会把这个簇切碎, 说明这条测试确实测到了差别
    naive = wrap_text_by_width(family, 25, font)
    assert len(naive) > 1
    assert "".join(naive) == family


def test_fit_reserves_the_height_the_emoji_mode_draws(
    font_file: Path,
) -> None:
    """fit 用 ascent+descent, 和 emoji 模式绘制时的行距一致, 块才不会溢出"""
    cache = FontCache(font_file=font_file)
    box_height = 60
    size, _ = calc_font_size(
        "A⭐\nB⭐",
        40,
        400,
        box_height,
        fontcache=cache,
        min_font_size=10,
        spacing=4,
        emoji_as_square=True,
    )
    line_height = sum(cache.use(size).getmetrics())
    assert 2 * line_height + 4 <= box_height


def test_nonsquare_icon_is_centered_in_its_square(
    font: ImageFont.FreeTypeFont, tmp_path: Path
) -> None:
    """宽 emoji (旗、心) 在字号方块里居中, 不能贴左边"""
    stub = _StubRenderer(_write_default_font(tmp_path / "center.otf"))
    stub.icon = Image.new("RGBA", (10, 20), BLOCK)  # 窄条, 方块宽 20
    canvas = Image.new("RGBA", (80, 40), _WHITE)
    draw_emoji_line(canvas, (10, 10), "⭐", font, stub, (0, 0, 0, 255))
    columns = np.nonzero(_red_mask(canvas).any(axis=0))[0]
    assert columns.size, "没有贴上色块"
    # 方块从 x=10 起、宽 20, 10 宽的图标应当落在 15..25
    assert int(columns.min()) >= 15
    assert int(columns.max()) <= 25
