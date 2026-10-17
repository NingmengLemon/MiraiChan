"""lemony_images: 图像处理工具集

子包:

- ``color``: 取色、配色与色彩空间换算
- ``text``: 文本度量、断行、绘制与彩色字体 emoji
"""

# --- 颜色工具 (完整接口见 lemony_images.color) ---
from .color import (
    ColorScheme,
    SchemeVariant,
    contrast_ratio,
    ensure_4inttuple,
    ensure_4inttuple_color,
    get_main_color,
    readable_tone,
    rel_lumin,
    scheme_from_color,
    source_color,
    source_colors,
    tone_of,
)

# --- 图像工具 ---
from .misc import (
    bytes_to_b64_url,
    calc_eudist,
    crop_to_circle,
    to_full_width,
)

# --- 文本 (完整接口见 lemony_images.text) ---
from .text import (
    ColorFontEmoji,
    FontCache,
    calc_bbox,
    calc_font_size,
    draw_multiline_text_auto,
    draw_outline,
    draw_text_line,
    fit_to_square,
    get_default_font_cache,
    init_default_font_cache,
    line_height,
    line_width,
    split_clusters,
    text_to_image,
    wrap_text_by_length,
    wrap_text_by_width,
)

__all__ = [
    "ColorFontEmoji",
    "ColorScheme",
    "FontCache",
    "SchemeVariant",
    "bytes_to_b64_url",
    "calc_bbox",
    "calc_eudist",
    "calc_font_size",
    "contrast_ratio",
    "crop_to_circle",
    "draw_multiline_text_auto",
    "draw_outline",
    "draw_text_line",
    "ensure_4inttuple",
    "ensure_4inttuple_color",
    "fit_to_square",
    "get_default_font_cache",
    "get_main_color",
    "init_default_font_cache",
    "line_height",
    "line_width",
    "readable_tone",
    "rel_lumin",
    "scheme_from_color",
    "source_color",
    "source_colors",
    "split_clusters",
    "text_to_image",
    "to_full_width",
    "tone_of",
    "wrap_text_by_length",
    "wrap_text_by_width",
]
