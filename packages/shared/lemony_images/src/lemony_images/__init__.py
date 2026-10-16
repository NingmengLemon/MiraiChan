"""lemony_images — 图像处理工具集"""

# --- 颜色工具 ---
from .color import (
    contrast_ratio,
    ensure_4inttuple,
    ensure_4inttuple_color,
    get_main_color,
    rel_lumin,
)

# --- emoji 源 ---
from .emoji import SelfHostSource

# --- 字体缓存 ---
from .font import (
    FontCache,
    get_default_font_cache,
    init_default_font_cache,
)

# --- 布局计算与绘制 ---
from .layout import (
    calc_bbox,
    calc_font_size,
    crop_to_circle,
    draw_multiline_text_auto,
    draw_outline,
    text_to_image,
    wrap_text_by_length,
    wrap_text_by_width,
)

# --- 图像工具 ---
from .misc import (
    bytes_to_b64_url,
    calc_eudist,
    to_full_width,
)

__all__ = [
    "FontCache",
    "SelfHostSource",
    "bytes_to_b64_url",
    "calc_bbox",
    "calc_eudist",
    "calc_font_size",
    "contrast_ratio",
    "crop_to_circle",
    "draw_multiline_text_auto",
    "draw_outline",
    "ensure_4inttuple",
    "ensure_4inttuple_color",
    "get_default_font_cache",
    "get_main_color",
    "init_default_font_cache",
    "rel_lumin",
    "text_to_image",
    "to_full_width",
    "wrap_text_by_length",
    "wrap_text_by_width",
]
