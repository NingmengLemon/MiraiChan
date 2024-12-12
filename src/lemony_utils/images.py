from io import BytesIO
import base64
import random
from typing import Any, Generator, Iterable, Literal, Type
from urllib.parse import quote_plus
from contextlib import contextmanager
import math
import asyncio

from melobot.protocols.onebot.v11.adapter.segment import ImageSegment
from PIL import ImageFont, ImageDraw, Image, ImageFilter
from pilmoji import Pilmoji
from pilmoji.source import HTTPBasedSource, BaseSource

_FontFileT = str | BytesIO
_TupleColorT = tuple[int, int, int] | tuple[int, int, int, int]
_ColorT = int | _TupleColorT | str
_BboxT = tuple[int, int, int, int]


class SelfHostSource(HTTPBasedSource):
    """因为神秘 pilmoji 不支持自定义 emoji 网络源所以自己写了

    ~~诸君，我喜欢 self-host~~"""

    STYLE = "google"

    def __init__(self, cdn: str):
        super().__init__()
        self._cdn = cdn.rstrip("/") + "/"

    def get_discord_emoji(self, id: int, /):  # pylint: disable=W0622
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

    def __init__(self, font_file: _FontFileT, preload_size_range: range | None = None):
        self._font_file = font_file
        self._font_map: dict[int, ImageFont.FreeTypeFont] = {}
        if preload_size_range:
            for size in preload_size_range:
                self._font_map[size] = ImageFont.truetype(font_file, size=size)

    def use(self, size: int):
        if size in self._font_map:
            return self._font_map[size]
        else:
            self._font_map[size] = ImageFont.truetype(self._font_file, size=size)
            return self._font_map[size]

    @contextmanager
    def usec(self, size: int):
        yield self.use(size=size)

    def __getitem__(self, key: int):
        return self.use(key)


_t2i_default_font = FontCache("data/fonts/sarasa-mono-sc-semibold.ttf")


def wrap_text_by_length(s: str, line_length: int):
    """根据字符长度断行"""
    result: list[str] = []
    for line in s.splitlines():
        for i in range(0, len(line), line_length):
            result.append(line[i : i + line_length])
    return result


def wrap_text_by_width(
    s: str,
    line_width: int,
    font: ImageFont.FreeTypeFont,
):
    """根据像素宽度断行"""
    result: list[str] = []
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


@contextmanager
def dummy_context_wrapper[T](obj: T) -> Generator[T, Any, None]:
    yield obj


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
    emoji_source: BaseSource | Type[BaseSource] | None = None,
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
    xy = calc_bbox(actual_bbox=finalbbox, expected_bbox=bbox, sticky=sticky)

    for kw in ("anchor", "direction", "font_size", "font"):
        kwargs.pop(kw, None)
    with (
        Pilmoji(
            image=draw._image, source=emoji_source, draw=draw  # pylint: disable=W0212
        )
        if emoji_source
        else dummy_context_wrapper(draw)
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


def rel_lumin(color: _TupleColorT) -> float:
    """相对亮度"""

    def conv(x: float):
        x = x / 255.0
        return (x / 12.92) if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = map(conv, color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color1: _ColorT, color2: _ColorT):
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


def calc_bbox(actual_bbox: _BboxT, expected_bbox: _BboxT, sticky: str | None):
    """根据给定的 小bbox (`actual_bbox`) 和 大bbox (`expected_bbox`) 和 停靠方向
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
    img = Image.new("RGBA", (1000, 1000))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font)
    width, height = right - left + 2 * margin, bottom - top + 2 * margin
    img = Image.new("RGBA", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    draw_point = (0 + margin, 0 + margin)
    draw.multiline_text(draw_point, text, font=font, fill=color, **kwargs)
    result = BytesIO()
    img.save(result, "PNG")
    return result.getvalue()


def bytes_to_b64_url(b: bytes):
    return "base64://" + base64.b64encode(b).decode("utf-8")


async def text_to_imgseg(text: str, /, **kwargs):
    return ImageSegment(
        file=await asyncio.to_thread(
            lambda: bytes_to_b64_url(text_to_image(text, **kwargs)),
        )
    )
