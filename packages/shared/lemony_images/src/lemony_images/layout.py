from contextlib import nullcontext
from io import BytesIO
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji
from pilmoji.source import BaseSource

from .color import ensure_4inttuple
from .font import FontCache, get_default_font_cache
from .typedef import _BboxT, _ColorT, _FontFileT


def wrap_text_by_length(s: str, line_length: int):
    """根据字符长度断行"""
    result: list[str] = []
    for line in s.splitlines():
        for i in range(0, len(line), line_length):
            result.append(line[i : i + line_length])
    return result


def wrap_text_by_width(
    s: str,
    line_width: int | float,
    font: ImageFont.FreeTypeFont,
):
    """根据像素宽度断行"""
    result: list[str] = []
    line_width = int(line_width)
    for line in s.splitlines():
        if not line:
            result.append("")
            continue
        char_widths = [font.getlength(c) for c in line]
        start = 0
        while start < len(line):
            current_width = 0
            end = start
            while end < len(line) and current_width + char_widths[end] <= line_width:
                current_width += char_widths[end]
                end += 1
            result.append(line[start:end])
            start = end
    return result


def calc_font_size(
    text: str,
    max_font_size: int,
    box_width: int,
    box_height: int,
    fontcache: FontCache,
    min_font_size: int = 20,
    spacing: int = 4,
):
    """计算出尽可能适合指定bbox的文本的字体大小，返回字号和断行后的文本内容

    当已经达到给定的最小字号但仍不能适合bbox高度时，返回最小字号，
    此时直接使用返回的字号和断行文本绘制文本将会超出bbox的高度"""
    fsize = max_font_size
    while fsize > min_font_size:
        font = fontcache.use(fsize)
        wrapped_lines = wrap_text_by_width(text, box_width, font)
        bbox = font.getbbox("意义是无意识")  # 这里要的是字体高度所以填什么都好x
        # getbbox 不认换行符所以像这样
        if (bbox[3] - bbox[1] + spacing) * len(wrapped_lines) <= box_height:
            break
        fsize -= 1
    return fsize, "\n".join(wrap_text_by_width(text, box_width, fontcache.use(fsize)))


def calc_bbox(
    actual_bbox: _BboxT,
    expected_bbox: _BboxT,
    sticky: str | None = None,
) -> tuple[int, int]:
    """
    根据给定的
    - 小bbox (`actual_bbox`)
    - 大bbox (`expected_bbox`)
    - 停靠方向 (`sticky`), 定义参考 tkinter 的 grid 布局中的 sticky 参数

    计算小bbox左上角点的坐标"""
    aw, ah = actual_bbox[2] - actual_bbox[0], actual_bbox[3] - actual_bbox[1]
    ew, eh = expected_bbox[2] - expected_bbox[0], expected_bbox[3] - expected_bbox[1]
    x, y = (
        expected_bbox[0] + (ew - aw) / 2,
        expected_bbox[1] + (eh - ah) / 2,
    )  # 初始居中
    if sticky:
        for s in sticky:
            match s:
                case "w":
                    x = expected_bbox[0]
                case "s":
                    y = expected_bbox[1] + eh - ah
                case "e":
                    x = expected_bbox[0] + ew - aw
                case "n":
                    y = expected_bbox[1]
    return int(x), int(y)


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
    emoji_source: BaseSource | type[BaseSource] | None = None,
    **kwargs: Any,
):
    """尽可能地在给定的bbox中绘制横向文本框，若达到最小字号后仍无法满足，绘制高度会超出预期高度

    `sticky` 参数的含义参考 tkinter 的 grid 布局中的 `sticky` 参数，指定为 `None` 时横纵居中

    多余的 kwargs 参数们会被递交给 `draw.text` 或 `Pilmoji.text`"""
    fontcache = font if isinstance(font, FontCache) else FontCache(font_file=font)
    font_size, wrapped_text = calc_font_size(
        text,
        max_font_size,
        bbox[2] - bbox[0],
        bbox[3] - bbox[1],
        fontcache=fontcache,
        min_font_size=min_font_size,
        spacing=spacing,
    )
    finalbbox = draw.multiline_textbbox(
        bbox[0:2],
        text=wrapped_text,
        font=fontcache.use(font_size),
        spacing=spacing,
        align=align,
    )
    xy = calc_bbox(
        actual_bbox=ensure_4inttuple(finalbbox), expected_bbox=bbox, sticky=sticky
    )

    for kw in (
        # 这些参数会导致计算错误, Pilmoji 也不支持
        "width",
        "anchor",
        "direction",
        "font_size",
        "font",
    ):
        kwargs.pop(kw, None)
    with (
        Pilmoji(
            image=draw._image,
            source=emoji_source,
            draw=draw,
        )
        if emoji_source
        else nullcontext(draw)
    ) as finaldraw:
        finaldraw.text(
            xy=xy,
            text=wrapped_text,
            fill=fill,
            font=fontcache.use(font_size),
            align=align,
            spacing=spacing,
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


def crop_to_circle(img: Image.Image):
    img = img.convert("RGBA")
    width, height = img.size

    size = min(width, height)
    left = (width - size) // 2
    top = (height - size) // 2
    right = left + size
    bottom = top + size
    img_cropped = img.crop((left, top, right, bottom))

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    img_cropped.putalpha(mask)

    return img_cropped.copy()


def text_to_image(
    text: str,
    font: ImageFont.FreeTypeFont | None | int = None,
    color: _ColorT = (255, 255, 255, 255),
    bg_color: _ColorT = (32, 32, 32, 255),
    margin: int = 10,
    wrap: int | None = 1920,
    **kwargs,
):
    if font is None:
        font = get_default_font_cache().use(20)
    elif isinstance(font, int):
        font = get_default_font_cache().use(font)
    if wrap is not None and wrap > 0:
        text = "\n".join(wrap_text_by_width(text, wrap, font))

    # dummy image to calculate text bbox
    # 经过测试发现 dummy image 的大小不会影响 getbbox 的结果
    img = Image.new("RGBA", (10, 10))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font)
    width, height = right - left + 2 * margin, bottom - top + 2 * margin

    # create final image
    img = Image.new("RGBA", (int(width), int(height)), color=bg_color)
    draw = ImageDraw.Draw(img)
    draw_point = (0 + margin, 0 + margin)
    draw.multiline_text(draw_point, text, font=font, fill=color, **kwargs)
    result = BytesIO()
    img.save(result, "PNG")
    return result.getvalue()
