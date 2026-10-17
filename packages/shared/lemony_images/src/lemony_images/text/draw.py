"""文本绘制。

emoji 由 ``ColorFontEmoji`` 画成图片贴在字号方块里, 其余文字交给字体; 不给
renderer 时整行都交给字体 (emoji 会落成字体里的方框)。

换行、行距与对齐都由调用方决定, 这里只管"一行"和"一块", 并且用
``lemony_images.text.metrics`` 的度量, 与 ``wrap.calc_font_size`` 一致。
"""

import math
from io import BytesIO
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont

from ..typedef import _BboxT, _ColorT, _FontFileT
from .emoji import ColorFontEmoji
from .font import FontCache, get_default_font_cache
from .geometry import calc_bbox, image_of
from .metrics import block_height, line_height, line_width, split_clusters
from .wrap import calc_font_size, measure_lines, wrap_text_by_width

__all__ = [
    "draw_multiline_text_auto",
    "draw_outline",
    "draw_text_line",
    "text_to_image",
]

# 这些参数会影响测量, 交给我们自己的排版处理, 不能再透传给 draw.text
_UNSUPPORTED_TEXT_KWARGS = ("width", "anchor", "direction", "font_size", "font")


def _normalize_newlines(text: str) -> str:
    """统一换行符。

    绘制与测量都按 ``\\n`` 切行, CRLF 留下来的 ``\\r`` 会被当成要画的字符,
    既占宽度又可能画出一个方块。
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def draw_text_line(
    image: Image.Image,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: Any = (0, 0, 0, 255),
    renderer: ColorFontEmoji | None = None,
    **text_kwargs: Any,
) -> float:
    """在 image 上画一行 (不含换行) 文本, 返回这一行的宽度。

    给了 renderer 时 emoji 簇由它画成图片, 在字号方块里横纵居中; 字体里没有的
    字形退回字体绘制。没给时整行交给字体。
    """
    x, y = xy
    draw = ImageDraw.Draw(image)
    started = x
    if renderer is None:
        draw.text((x, y), text, font=font, fill=fill, **text_kwargs)
        return font.getlength(text)
    row_height = line_height(font)
    for chunk, is_emoji in split_clusters(text):
        if not is_emoji:
            draw.text((x, y), chunk, font=font, fill=fill, **text_kwargs)
            x += font.getlength(chunk)
            continue
        size = int(font.size)
        icon = renderer.render(chunk, target=size)
        if icon is None:
            draw.text((x, y), chunk, font=font, fill=fill, **text_kwargs)
        else:
            # 非方形的 emoji (旗、心) 在方块里居中, 不能贴左边
            left = round(x + (size - icon.width) / 2)
            top = round(y + (row_height - icon.height) / 2)
            if image.mode == "RGBA":
                image.alpha_composite(icon, (left, top))
            else:
                image.paste(icon, (left, top), icon)
        x += size
    return x - started


def draw_multiline_text_auto(
    bbox: _BboxT,
    draw: ImageDraw.ImageDraw,
    text: str,
    font: _FontFileT | FontCache,
    max_font_size: int,
    min_font_size: int = 10,
    fill: _ColorT = (0, 0, 0, 255),
    align: Literal["left", "right", "center"] = "left",
    spacing: int = 4,
    sticky: str | None = None,
    emoji_renderer: ColorFontEmoji | None = None,
    **kwargs: Any,
):
    """尽可能地在给定的 bbox 里画一块多行文本, 到最小字号还放不下就会超出高度

    ``sticky`` 见 ``geometry.calc_bbox``: ``None`` 时横纵居中。

    给了 ``emoji_renderer`` 时 emoji 簇用彩色字体画成图片贴上, 占一个字号宽的方块;
    没给时全部交给字体。多余的 kwargs 会递给 ``draw.text``。
    """
    fontcache = font if isinstance(font, FontCache) else FontCache(font_file=font)
    emoji_as_square = emoji_renderer is not None
    text = _normalize_newlines(text)
    font_size, wrapped_text = calc_font_size(
        text,
        max_font_size,
        bbox[2] - bbox[0],
        bbox[3] - bbox[1],
        fontcache=fontcache,
        min_font_size=min_font_size,
        spacing=spacing,
        emoji_as_square=emoji_as_square,
    )
    use_font = fontcache.use(font_size)
    for kw in _UNSUPPORTED_TEXT_KWARGS:
        kwargs.pop(kw, None)

    lines = wrapped_text.split("\n")
    widths = measure_lines(wrapped_text, use_font, emoji_as_square=emoji_as_square)
    row_height = line_height(use_font)
    block_width = max(widths, default=0.0)
    total_height = block_height(len(lines), row_height, spacing)
    xy = calc_bbox(
        actual_bbox=(
            bbox[0],
            bbox[1],
            bbox[0] + math.ceil(block_width),
            bbox[1] + total_height,
        ),
        expected_bbox=bbox,
        sticky=sticky,
    )
    image = image_of(draw)
    for i, (line, width) in enumerate(zip(lines, widths, strict=True)):
        match align:
            case "center":
                x = xy[0] + (block_width - width) / 2
            case "right":
                x = xy[0] + block_width - width
            case _:
                x = float(xy[0])
        draw_text_line(
            image,
            (x, xy[1] + i * (row_height + spacing)),
            line,
            use_font,
            fill=fill,
            renderer=emoji_renderer,
            **kwargs,
        )


def draw_outline(
    outline_color: _ColorT,
    outline_width: int,
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    **kwargs: Any,
):
    """绘制出文本轮廓

    *未经测试*"""
    if outline_width <= 0:
        return
    x, y = xy
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, fill=outline_color, **kwargs)


def _line_extent(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    emoji_as_square: bool,
    stroke_width: float,
) -> tuple[float, float, float, float]:
    """一行画出来之后实际占的范围 (left, top, right, bottom), 相对锚点 (0, 0)

    宽度取 advance 与墨迹右缘的较大值: 斜体、花体这些字形会伸出 advance,
    只按 advance 开画布会把右边裁掉。左侧与上方可能为负 (负 bearing), 交给
    调用方整体平移。描边是向外扩的, 四个方向都要留出来。
    """
    ink = font.getbbox(text)
    advance = line_width(text, font, emoji_as_square=emoji_as_square)
    left = min(0.0, ink[0]) - stroke_width
    top = min(0.0, ink[1]) - stroke_width
    right = max(advance, ink[2]) + stroke_width
    bottom = max(line_height(font), ink[3]) + stroke_width
    return left, top, right, bottom


def text_to_image(
    text: str,
    font: ImageFont.FreeTypeFont | int | None = None,
    color: _ColorT = (255, 255, 255, 255),
    bg_color: _ColorT = (32, 32, 32, 255),
    margin: int = 10,
    wrap: int | None = 1920,
    emoji_renderer: ColorFontEmoji | None = None,
    spacing: int = 4,
    **kwargs: Any,
) -> bytes:
    """把一段文本画成 PNG, 返回图片字节

    画布按实际墨迹 (含斜体出框与描边) 开, 不会裁掉字。给了 ``emoji_renderer``
    时 emoji 会被画成彩色字形, 否则交给正文字体。
    """
    if font is None:
        font = get_default_font_cache().use(20)
    elif isinstance(font, int):
        font = get_default_font_cache().use(font)
    text = _normalize_newlines(text)
    emoji_as_square = emoji_renderer is not None
    if wrap is not None and wrap > 0:
        text = "\n".join(
            wrap_text_by_width(text, wrap, font, emoji_as_square=emoji_as_square)
        )

    lines = text.split("\n")
    row_height = line_height(font)
    stroke = float(kwargs.get("stroke_width") or 0)
    extents = [
        _line_extent(line, font, emoji_as_square=emoji_as_square, stroke_width=stroke)
        for line in lines
    ]
    left = min(e[0] for e in extents)
    top = min(e[1] for e in extents)
    right = max(e[2] for e in extents)
    step = row_height + spacing
    bottom = (len(lines) - 1) * step + max(e[3] for e in extents)
    size = (
        max(1, math.ceil(right - left) + 2 * margin),
        max(1, math.ceil(bottom - top) + 2 * margin),
    )
    img = Image.new("RGBA", size, color=bg_color)
    for i, line in enumerate(lines):
        draw_text_line(
            img,
            (margin - left, margin - top + i * step),
            line,
            font,
            fill=color,
            renderer=emoji_renderer,
            **kwargs,
        )
    result = BytesIO()
    img.save(result, "PNG")
    return result.getvalue()
