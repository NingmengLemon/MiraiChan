# TODO: split into other modules
import base64
import math
import os
import random
from collections.abc import Iterable
from contextlib import contextmanager, nullcontext
from io import BytesIO
from typing import Any, BinaryIO, Literal
from urllib.parse import quote_plus

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pilmoji import Pilmoji
from pilmoji.source import BaseSource, HTTPBasedSource

type _FontFileT = str | bytes | os.PathLike[str] | os.PathLike[bytes] | BinaryIO
type _4IntTupleT = tuple[int, int, int, int]
type _3IntTupleT = tuple[int, int, int]
type _ColorTupleT = _3IntTupleT | _4IntTupleT
type _ColorT = int | _ColorTupleT | str
type _BboxT = _4IntTupleT


class SelfHostSource(HTTPBasedSource):
    """因为神秘 pilmoji 不支持自定义 emoji 网络源所以自己写了

    ~~诸君，我喜欢 self-host~~"""

    STYLE = "google"

    def __init__(self, cdn: str):
        super().__init__()
        self._cdn = cdn.rstrip("/") + "/"

    def get_discord_emoji(self, id: int, /):
        return None

    def get_emoji(self, emoji: str, /):
        try:
            return BytesIO(
                self.request(self._cdn + quote_plus(emoji) + "?style=google")
            )
        except Exception:
            return None


class FontCache:
    """因为发现 ImageDraw.text 方法中的 font_size 参数不起效，
    于是弄了个这样的类来做字体缓存"""

    def __init__(
        self, font_file: _FontFileT, preload_sizes: Iterable[int] | None = None
    ):
        self._font_file = font_file
        self._font_map: dict[int, ImageFont.FreeTypeFont] = {}
        if preload_sizes:
            for size in preload_sizes:
                self._font_map[size] = ImageFont.truetype(font_file, size=size)

    def use(self, size: int):
        size = int(size)
        if size not in self._font_map:
            self._font_map[size] = ImageFont.truetype(self._font_file, size=size)
        return self._font_map[size]

    @contextmanager
    def usec(self, size: int):
        yield self.use(size=size)

    def __getitem__(self, key: int):
        return self.use(key)


_t2i_default_font = FontCache("data/fonts/sarasa-mono-sc-semibold.ttf")
default_font_cache = _t2i_default_font


def ensure_4inttuple(obj: tuple[Any, Any, Any, Any]) -> _4IntTupleT:
    return (int(obj[0]), int(obj[1]), int(obj[2]), int(obj[3]))


def ensure_4inttuple_color(
    color: _ColorT
    | tuple[float | int, float | int, float | int, float | int]
    | tuple[float | int, float | int, float | int],  # 兼容不规范的输入
) -> _4IntTupleT:
    """确保颜色是 RGBA 四元组形式"""
    if isinstance(color, int):
        if color <= 0xFFFFFF:
            r = (color >> 16) & 0xFF
            g = (color >> 8) & 0xFF
            b = color & 0xFF
            a = 255
        else:
            r = (color >> 24) & 0xFF
            g = (color >> 16) & 0xFF
            b = (color >> 8) & 0xFF
            a = color & 0xFF
        return (r, g, b, a)
    elif isinstance(color, str):
        color = color.lstrip("#")
        if len(color) == 6:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            a = 255
        elif len(color) == 8:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            a = int(color[6:8], 16)
        else:
            raise ValueError(f"Invalid color string: {color}")
        return (r, g, b, a)
    elif isinstance(color, tuple):
        if len(color) == 3:
            r, g, b = color
            a = 255
        elif len(color) == 4:
            r, g, b, a = color
        else:
            raise ValueError(f"Invalid color tuple: {color}")
        return ensure_4inttuple((r, g, b, a))
    else:
        raise TypeError(f"Unsupported color type: {type(color)}")


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


def to_full_width(text: str):
    """半角英文字符转全角"""
    return "".join([chr(ord(c) + 0xFEE0) if 33 <= ord(c) <= 126 else c for c in text])


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
        with fontcache.usec(size=fsize) as font:
            wrapped_lines = wrap_text_by_width(text, box_width, font)
            bbox = font.getbbox("意义是无意识")  # 这里要的是字体高度所以填什么都好x
            # getbbox 不认换行符所以像这样
            if (bbox[3] - bbox[1] + spacing) * len(wrapped_lines) <= box_height:
                break
        fsize -= 1
    return fsize, "\n".join(wrap_text_by_width(text, box_width, fontcache.use(fsize)))


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
    **kwargs,
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


def calc_eudist(p1: Iterable[float], p2: Iterable[float]):
    """欧几里得空间距离"""
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(p1, p2)))


def rel_lumin(color: _ColorTupleT) -> float:
    """相对亮度"""

    def conv(x: float):
        x = x / 255.0
        return (x / 12.92) if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = map(conv, color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color1: _ColorTupleT, color2: _ColorTupleT):
    """对比度"""
    l1 = rel_lumin(color1)
    l2 = rel_lumin(color2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def draw_outline(
    outline_color: _ColorT,
    outline_width: int,
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    **kwargs,
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


def get_main_color(image: Image.Image, radius: None | float = None, resize: int = 50):
    """通过 缩小图像 + 高斯模糊 + 随机取样 取得主要颜色

    Inspired by Moncak

    ~~没错插件 `EroMoncak` 的名字里的 `Moncak` 就是这只萝莉~~"""
    blurred = image.resize((resize, resize)).filter(
        ImageFilter.GaussianBlur(resize if radius is None else radius)
    )
    w, h = blurred.size
    return blurred.getpixel((random.randint(0, w - 1), random.randint(0, h - 1)))


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
        font = _t2i_default_font.use(20)
    elif isinstance(font, int):
        font = _t2i_default_font.use(font)
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


def bytes_to_b64_url(b: bytes):
    return "base64://" + base64.b64encode(b).decode("utf-8")


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
