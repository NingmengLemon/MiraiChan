"""文本度量、断行与绘制。

真实彩色字体不在仓库里, 这里用 Pillow 自带字体加一个固定返回色块的渲染器,
验证的是"测量与绘制用同一套规则"以及贴图路径本身。
"""

import math
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from lemony_images.text import (
    ColorFontEmoji,
    FontCache,
    block_height,
    calc_font_size,
    draw_multiline_text_auto,
    draw_text_line,
    line_height,
    line_width,
    text_to_image,
    wrap_text_by_width,
)
from PIL import Image, ImageDraw, ImageFont

BLOCK = (255, 0, 0, 255)  # 用一个纯红方块代替字形
_WHITE = (255, 255, 255, 255)


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


@pytest.fixture
def font(font_file: Path) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_file), 20)


@pytest.fixture
def renderer(font_file: Path) -> _StubRenderer:
    stub = _StubRenderer(font_file)
    stub.icon = Image.new("RGBA", (20, 20), BLOCK)
    return stub


def test_emoji_cluster_takes_one_square(font: ImageFont.FreeTypeFont) -> None:
    assert line_width("⭐", font, emoji_as_square=True) == pytest.approx(font.size)
    # ZWJ 序列整体算一块, 不是每个码位一块
    assert line_width("👨‍👩‍👧‍👦", font, emoji_as_square=True) == pytest.approx(
        font.size
    )


def test_plain_text_uses_measured_width(font: ImageFont.FreeTypeFont) -> None:
    assert line_width("hello", font, emoji_as_square=True) == pytest.approx(
        font.getlength("hello")
    )
    mixed = line_width("a⭐b", font, emoji_as_square=True)
    assert mixed == pytest.approx(font.getlength("ab") + font.size)
    # 不按方块算时完全交给字体实测 (纯文本绘制的模式)
    assert line_width("a⭐b", font, emoji_as_square=False) == pytest.approx(
        font.getlength("a⭐b")
    )


def test_draw_text_line_reports_width_and_composites(
    font: ImageFont.FreeTypeFont, renderer: _StubRenderer
) -> None:
    canvas = Image.new("RGBA", (120, 40), _WHITE)
    width = draw_text_line(
        canvas, (4, 4), "a⭐b", font, fill=(0, 0, 0, 255), renderer=renderer
    )
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
    """fit 与绘制用同一个行高, 块才不会溢出"""
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
    assert 2 * line_height(cache.use(size)) + 4 <= box_height


def test_fit_returns_the_size_that_exactly_fits(font_file: Path) -> None:
    """盒子刚好等于该字号的块高时, fit 必须选它, 不能因为多算一个 spacing 退一档"""
    cache = FontCache(font_file=font_file)
    size = 40
    exact = block_height(2, line_height(cache.use(size)), 4)
    got, _ = calc_font_size(
        "A\nB",
        size,
        400,
        exact,
        fontcache=cache,
        min_font_size=10,
        spacing=4,
    )
    assert got == size


def _ink_rows(canvas: Image.Image) -> np.ndarray:
    """非背景色的行号; 画布要比 bbox 大, 否则溢出会被裁掉、断言就成了摆设"""
    arr = np.array(canvas.convert("RGB"))
    return np.nonzero((arr != np.array(_WHITE[:3])).any(axis=2).any(axis=1))[0]


def test_drawn_block_stays_inside_the_box(
    font_file: Path, renderer: _StubRenderer
) -> None:
    """端到端: 画出来的墨迹确实落在 bbox 里 (emoji 模式不许溢出)"""
    # 画布高 200 而 bbox 只到 60: 真溢出会画到 60 以下, 才看得出来
    canvas = Image.new("RGBA", (400, 200), _WHITE)
    draw_multiline_text_auto(
        (0, 0, 400, 60),
        ImageDraw.Draw(canvas),
        "A⭐\nB⭐",
        FontCache(font_file=font_file),
        max_font_size=40,
        spacing=4,
        sticky="n",
        emoji_renderer=renderer,
    )
    rows = _ink_rows(canvas)
    assert rows.size, "什么都没画出来"
    assert int(rows.max()) < 60


def test_plain_drawn_block_stays_inside_the_box(font_file: Path) -> None:
    """纯文本路径同样不许溢出 bbox"""
    canvas = Image.new("RGBA", (400, 200), _WHITE)
    draw_multiline_text_auto(
        (0, 0, 400, 60),
        ImageDraw.Draw(canvas),
        "A\nB",
        FontCache(font_file=font_file),
        max_font_size=40,
        spacing=4,
        sticky="n",
    )
    rows = _ink_rows(canvas)
    assert rows.size, "什么都没画出来"
    assert int(rows.max()) < 60


def test_nonsquare_icon_is_centered_in_its_square(
    font: ImageFont.FreeTypeFont, font_file: Path
) -> None:
    """宽 emoji (旗、心) 在字号方块里居中, 不能贴左边"""
    stub = _StubRenderer(font_file)
    stub.icon = Image.new("RGBA", (10, 20), BLOCK)  # 窄条, 方块宽 20
    canvas = Image.new("RGBA", (80, 40), _WHITE)
    draw_text_line(canvas, (10, 10), "⭐", font, fill=(0, 0, 0, 255), renderer=stub)
    columns = np.nonzero(_red_mask(canvas).any(axis=0))[0]
    assert columns.size, "没有贴上色块"
    # 方块从 x=10 起、宽 20, 10 宽的图标应当落在 15..25
    assert int(columns.min()) >= 15
    assert int(columns.max()) <= 25


def test_text_to_image_draws_emoji(font_file: Path, renderer: _StubRenderer) -> None:
    font = ImageFont.truetype(str(font_file), 20)
    data = text_to_image("A⭐B", font=font, emoji_renderer=renderer)
    image = Image.open(BytesIO(data)).convert("RGBA")
    assert _red_mask(image).any()


def test_text_to_image_plain_does_not_draw_a_block(font_file: Path) -> None:
    font = ImageFont.truetype(str(font_file), 20)
    data = text_to_image("A⭐B", font=font)
    image = Image.open(BytesIO(data)).convert("RGBA")
    assert not _red_mask(image).any()


def test_text_to_image_wraps_at_the_given_width(font_file: Path) -> None:
    font = ImageFont.truetype(str(font_file), 20)
    narrow = Image.open(BytesIO(text_to_image("ab " * 20, font=font, wrap=100)))
    wide = Image.open(BytesIO(text_to_image("ab " * 20, font=font, wrap=10_000)))
    assert narrow.height > wide.height
    assert narrow.width < wide.width


def _ink_margins(image: Image.Image) -> tuple[int, int, int, int]:
    """墨迹到四边各留了多少像素"""
    arr = np.array(image.convert("RGBA"))
    mask = (arr[:, :, :3] != np.array([32, 32, 32])).any(axis=2)
    ys, xs = np.nonzero(mask)
    assert xs.size, "图上什么也没画"
    return (
        int(xs.min()),
        int(ys.min()),
        int(image.width - 1 - xs.max()),
        int(image.height - 1 - ys.max()),
    )


def test_text_to_image_canvas_covers_ink_wider_than_the_advance(
    font_file: Path,
) -> None:
    """宽度不能只按 advance 开: 墨迹会伸出 advance, 只按 advance 就裁字

    这条用例要能区分新旧实现, 所以先确认这个字形真的出框。
    """
    font = ImageFont.truetype(str(font_file), 100)
    ink = font.getbbox("K")
    advance = font.getlength("K")
    assert ink[2] > advance, "这个字体里 K 没有出框, 换一个字形或字号"
    image = Image.open(BytesIO(text_to_image("K", font=font, margin=0)))
    assert image.width >= math.ceil(ink[2] - min(0.0, ink[0]))
    # 只按 advance 开画布会比墨迹窄
    assert image.width > math.ceil(advance)


def test_text_to_image_keeps_stroked_ink_inside_the_canvas(
    font_file: Path,
) -> None:
    """描边往外扩得比留白还宽时, 画布必须把描边算进去, 否则四边都会被裁"""
    font = ImageFont.truetype(str(font_file), 40)
    # 描边比 margin 宽, 忽略描边的实现会贴到边上 (余量 0)
    image = Image.open(
        BytesIO(text_to_image("j", font=font, margin=2, stroke_width=12))
    )
    margins = _ink_margins(image)
    assert min(margins) > 0
    assert min(margins) >= 2


def test_text_to_image_without_margin_never_produces_an_empty_canvas(
    font_file: Path,
) -> None:
    font = ImageFont.truetype(str(font_file), 20)
    image = Image.open(BytesIO(text_to_image("", font=font, margin=0)))
    assert image.width >= 1
    assert image.height >= 1


def test_text_to_image_keeps_trailing_blank_lines(font_file: Path) -> None:
    """尾随空行不能被吞掉, 否则多行文本的高度会少算一行"""
    font = ImageFont.truetype(str(font_file), 20)
    one = Image.open(BytesIO(text_to_image("A", font=font, wrap=10_000)))
    two = Image.open(BytesIO(text_to_image("A\n", font=font, wrap=10_000)))
    assert two.height > one.height


def test_text_to_image_treats_crlf_like_lf(font_file: Path) -> None:
    """CRLF 的 \\r 不能被当成要画的字符, 否则宽度与行数都会变"""
    font = ImageFont.truetype(str(font_file), 20)
    lf = Image.open(BytesIO(text_to_image("ab\ncd", font=font, wrap=10_000)))
    crlf = Image.open(BytesIO(text_to_image("ab\r\ncd", font=font, wrap=10_000)))
    assert crlf.size == lf.size
