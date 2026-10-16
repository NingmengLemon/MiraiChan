"""颜色工具。颜色在边界上统一用 RGBA 四元组 ``(r, g, b, a)``, 0 ~ 255, 可直接交给 Pillow。

- ``convert``: 各种写法与 RGBA / ARGB / hex 之间的转换
- ``contrast``: WCAG 2 相对亮度与对比度
- ``mix``: 在 OKLab / OKLCh 里混色、调明暗
- ``extract``: 从图片里取颜色的简单方法
- ``dynamic``: Material Design 3 动态取色 (源色、HCT 明度、整套配色)
"""

from .contrast import contrast_ratio, readable_on, rel_lumin
from .convert import (
    argb_to_rgba,
    ensure_4inttuple,
    ensure_4inttuple_color,
    rgba_to_argb,
    to_hex,
    with_alpha,
)
from .dynamic import (
    ColorScheme,
    SchemeVariant,
    readable_tone,
    scheme_from_color,
    source_color,
    source_colors,
    tone_of,
)
from .extract import average_color, get_main_color
from .mix import darken, lighten, mix

__all__ = [
    "ColorScheme",
    "SchemeVariant",
    "argb_to_rgba",
    "average_color",
    "contrast_ratio",
    "darken",
    "ensure_4inttuple",
    "ensure_4inttuple_color",
    "get_main_color",
    "lighten",
    "mix",
    "readable_on",
    "readable_tone",
    "rel_lumin",
    "rgba_to_argb",
    "scheme_from_color",
    "source_color",
    "source_colors",
    "to_hex",
    "tone_of",
    "with_alpha",
]
