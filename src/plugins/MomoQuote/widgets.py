from collections.abc import Iterable

from PIL import Image, ImageOps, ImageDraw
from pilmoji.source import BaseSource
from pilmoji import Pilmoji

from lemony_utils.images import (
    FontCache,
    _ColorT,
    crop_to_circle,
    wrap_text_by_width,
    dummy_context_wrapper,
)

__all__ = ["Avatar", "Bubble"]


def _ensure_int(l: Iterable):
    return tuple(map(int, l))


class Avatar:
    def __init__(
        self,
        image: Image.Image,
        width: int = 90,
        scale: float = 1.0,
    ):
        self._image = crop_to_circle(image)
        self._width = width
        self._scale = scale

    def size(self):
        return (self._width * self._scale, self._width * self._scale)

    def draw(
        self,
        canvas: Image.Image,
        coor: tuple[int, int],
        bg_color: _ColorT = "#ffffffff",
        show_border: bool = False,
    ):
        s = self._scale
        n = int(self._width * s)
        x, y = map(lambda _n: int(_n * s), coor)

        img = Image.new("RGBA", (n, n), color=bg_color)
        img.alpha_composite(ImageOps.fit(self._image, (n, n)))
        canvas.paste(img, (x, y))

        if show_border:
            draw = ImageDraw.Draw(canvas)
            draw.rectangle([x, y, x + n, y + n], outline="#66ccffff", width=int(4 * s))


class Bubble:
    def __init__(
        self,
        elements: Iterable[str | Image.Image],
        font: FontCache,
        wrap_width: int = 512,
        radius: int = 10,
        font_size: int = 28,
        padding: int = 12,
        spacing: int = 10,
        bg_color: _ColorT = "#4c5b6f",
        text_color: _ColorT = "#ffffff",
        scale: float = 1.0,
    ):
        self._font = font
        self._wrap_width = wrap_width
        self._radius = radius
        self._font_size = font_size
        self._padding = padding
        self._spacing = spacing
        self._bg_color = bg_color
        self._text_color = text_color
        self._scale = scale

        # 预处理
        # 文本按像素断行, 图片按比例缩放
        # 算出最终每个元素的长宽
        self._heights: list[int | float] = []
        self._widths: list[int | float] = []
        self._elements: list[str | Image.Image] = []

        draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        for elem in elements:
            if isinstance(elem, str):
                text = "\n".join(
                    wrap_text_by_width(
                        elem, wrap_width * scale, font.use(font_size * scale)
                    )
                )
                _, _, w, h = draw.multiline_textbbox(
                    (0, 0),
                    text,
                    font=font.use(font_size * scale),
                    spacing=spacing * scale,
                )

                self._elements.append(text)
                self._widths.append(w)
                self._heights.append(h)
            elif isinstance(elem, Image.Image):
                e = elem if elem.mode == "RGBA" else elem.convert("RGBA")
                w, h = e.size
                k = (wrap_width * scale) / w if w > wrap_width else scale
                self._elements.append(
                    e := ImageOps.contain(e, (int(w * k), int(h * k)))
                )
                self._widths.append(e.size[0])
                self._heights.append(e.size[1])

    @property
    def size(self):
        return (
            max(self._widths) + self._padding * self._scale * 2,
            (self._padding * (len(self._heights) + 1)) * self._scale
            + sum(self._heights),
        )

    def draw(
        self,
        canvas: Image.Image,
        coor: tuple[int, int],
        emoji_source: BaseSource | type[BaseSource] | None = None,
        add_triangle: bool = False,
        show_border: bool = False,
    ):
        # 来点神秘简写
        s = self._scale
        p = self._padding
        font = self._font.use(self._font_size * s)

        draw = ImageDraw.Draw(canvas)
        # 先把圆角矩形画在画布最底部
        w, h = self.size
        x, y = map(lambda n: n * s, coor)
        # xy 现在在气泡的左上角
        draw.rounded_rectangle(
            _ensure_int((x, y, x + w, y + h)),
            radius=self._radius * s,
            fill=self._bg_color,
        )
        if add_triangle:
            draw.polygon(
                _ensure_int(
                    [
                        x,
                        y + 15 * s,
                        x,
                        y + 25 * s,
                        x - 10 * s,
                        y + 20 * s,
                    ]
                ),
                fill=self._bg_color,
            )
        x, y = x + p * s, y + p * s
        # xy 偏移 padding 个像素到气泡内第一个元素的左上角
        for elem, w, h in zip(self._elements, self._widths, self._heights):
            if isinstance(elem, str):
                text = elem
                with (
                    Pilmoji(canvas, source=emoji_source, draw=draw)
                    if emoji_source
                    else dummy_context_wrapper(draw)
                ) as finaldraw:
                    finaldraw.text(
                        _ensure_int((x, y)),
                        text,
                        fill=self._text_color,
                        font=font,
                        spacing=self._spacing * s,
                    )
            elif isinstance(elem, Image.Image):
                img = Image.new("RGBA", elem.size, color=self._bg_color)
                img.alpha_composite(elem)
                canvas.paste(img, _ensure_int((x, y)))
            if show_border:
                draw.rectangle(
                    _ensure_int([x, y, x + w, y + h]),
                    outline="#66ccffff",
                    width=int(4 * s),
                )
            y += h + p * s
            # 完成一个元素后移动 y 坐标以绘制下一个元素
