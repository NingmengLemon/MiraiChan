"""``lemony_images.text``: 文本度量、断行、绘制与 emoji 字形。

分层:

- ``metrics``: 一行多高、一个单元多宽, 全库唯一的度量定义
- ``font``: 字体缓存
- ``emoji``: 从彩色字体光栅化 emoji 字形
- ``wrap``: 按宽度断行与字号拟合
- ``geometry``: bbox 摆位
- ``draw``: 画一行 / 画一块 / 文本转图

引用图插件自带一套块排版 (按词断行、超行截断), 度量也从 ``metrics`` 取。
"""

from .draw import (
    draw_multiline_text_auto,
    draw_outline,
    draw_text_line,
    text_to_image,
)
from .emoji import ColorFontEmoji, fit_to_square
from .font import FontCache, get_default_font_cache, init_default_font_cache
from .geometry import calc_bbox
from .metrics import (
    block_height,
    emoji_square_width,
    line_height,
    line_width,
    split_clusters,
    unit_width,
)
from .wrap import (
    calc_font_size,
    measure_lines,
    wrap_text_by_length,
    wrap_text_by_width,
)

__all__ = [
    "ColorFontEmoji",
    "FontCache",
    "block_height",
    "calc_bbox",
    "calc_font_size",
    "draw_multiline_text_auto",
    "draw_outline",
    "draw_text_line",
    "emoji_square_width",
    "fit_to_square",
    "get_default_font_cache",
    "init_default_font_cache",
    "line_height",
    "line_width",
    "measure_lines",
    "split_clusters",
    "text_to_image",
    "unit_width",
    "wrap_text_by_length",
    "wrap_text_by_width",
]
