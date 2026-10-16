"""Material Design 3 动态取色: 从图片取源色, 再按 HCT 色彩空间生成配色。

基于 ``material-color-utilities`` (MCU)。颜色在边界上统一用 RGBA 四元组, 可直接交给 Pillow;
MCU 内部的 ARGB 整数只在本模块里出现。

典型用法::

    src = source_color(avatar)              # 无彩色图片得到 None
    if src is not None:
        scheme = scheme_from_color(src, dark=True)
        fg = scheme["primary"]
        fg = readable_tone(src, background=panel, min_contrast=4.5, prefer=80)

耗时 (本机实测): 640px 头像取源色约 11 ms (MCU 会先缩到 128x128)。由源色生成配色的耗时
看变体: CONTENT 约 60 ms, FIDELITY 约 7 ms, 其余约 0.3 ms。配色按源色缓存,
同一个头像 (源色相同) 只付一次。
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from types import MappingProxyType

import numpy as np
from material_color_utilities import Hct, TonalPalette, Variant, theme_from_argb_color
from material_color_utilities._core import prominent_colors_from_array_argb
from material_color_utilities.image_utils import image_to_argb
from PIL import Image

from .color import contrast_ratio
from .typedef import _4IntTupleT, _ColorTupleT

__all__ = [
    "ColorScheme",
    "SchemeVariant",
    "argb_to_rgba",
    "readable_tone",
    "rgba_to_argb",
    "scheme_from_color",
    "source_color",
    "source_colors",
    "tone_of",
]

# MCU 在图里找不到合格的彩色时会回退到这个颜色 (Google Blue), 而不是返回空列表
_MCU_FALLBACK = 0xFF4285F4
# 回退色本身在图里至少要占这个比例, 才认为是真的取到了它
_FALLBACK_MIN_SHARE = 0.01
_FALLBACK_MAX_DIST = 24.0


class SchemeVariant(StrEnum):
    """配色变体, 与 MCU 的 Variant 一一对应。

    取头像这类"要像原图"的场景用 FIDELITY / CONTENT (两者常见角色基本一致,
    CONTENT 慢得多); TONALSPOT 是 Android 默认,
    饱和度会被压低。
    """

    MONOCHROME = "monochrome"
    NEUTRAL = "neutral"
    TONALSPOT = "tonalspot"
    VIBRANT = "vibrant"
    EXPRESSIVE = "expressive"
    FIDELITY = "fidelity"
    CONTENT = "content"
    RAINBOW = "rainbow"
    FRUITSALAD = "fruitsalad"


def argb_to_rgba(argb: int) -> _4IntTupleT:
    return ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF, (argb >> 24) & 0xFF)


def rgba_to_argb(color: _ColorTupleT) -> int:
    a = color[3] if len(color) == 4 else 255
    return (a << 24) | (color[0] << 16) | (color[1] << 8) | color[2]


def _hex_to_rgba(hex_color: str) -> _4IntTupleT:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _really_contains_fallback(pixels: np.ndarray) -> bool:
    """判断 MCU 给出的回退色是不是图里真有的颜色"""
    opaque = pixels[(pixels >> 24) == 0xFF]
    if opaque.size == 0:
        return False
    rgb = np.stack(
        [(opaque >> 16) & 0xFF, (opaque >> 8) & 0xFF, opaque & 0xFF], axis=1
    ).astype(np.float64)
    target = np.array([0x42, 0x85, 0xF4], dtype=np.float64)
    near = np.linalg.norm(rgb - target, axis=1) <= _FALLBACK_MAX_DIST
    return bool(near.mean() >= _FALLBACK_MIN_SHARE)


def source_colors(image: Image.Image, max_colors: int = 128) -> list[_4IntTupleT]:
    """按 MCU 评分从高到低返回图片的候选源色; 无彩色 (灰度 / 全透明) 图片返回空列表。

    半透明像素不参与统计。
    """
    pixels = image_to_argb(image)
    found = prominent_colors_from_array_argb(pixels, max_colors)
    if found == [_MCU_FALLBACK] and not _really_contains_fallback(pixels):
        return []
    return [argb_to_rgba(c) for c in found]


def source_color(image: Image.Image) -> _4IntTupleT | None:
    """图片评分最高的源色; 无彩色图片返回 None, 由调用方决定中性色"""
    found = source_colors(image)
    return found[0] if found else None


def tone_of(color: _ColorTupleT, tone: float) -> _4IntTupleT:
    """保持色相与色度, 把颜色换到指定明度 (HCT tone, 0 黑 ~ 100 白)。

    色度超出该明度下 sRGB 能表示的范围时 MCU 会自动收窄。
    """
    # MCU 的类型桩把重载写成了连续的 __init__ (没加 @overload), ty 只认最后一个
    hct = Hct(rgba_to_argb(color))  # ty: ignore[invalid-argument-type]
    palette = TonalPalette(hct.hue, hct.chroma)  # ty: ignore[missing-argument]
    return argb_to_rgba(palette.get_argb(tone))


def readable_tone(
    color: _ColorTupleT,
    *,
    background: _ColorTupleT,
    min_contrast: float = 4.5,
    prefer: float = 80,
) -> _4IntTupleT:
    """在 color 的色相与色度下, 找离 prefer 最近且与背景对比度达标的明度。

    对比度按 WCAG 2 计算。所有明度都不达标时 (背景是中灰之类) 返回黑白中对比度更高的那个。
    """
    tones = sorted(range(101), key=lambda t: (abs(t - prefer), t))
    for t in tones:
        candidate = tone_of(color, t)
        if contrast_ratio(candidate, background) >= min_contrast:
            return candidate
    white: _4IntTupleT = (255, 255, 255, 255)
    black: _4IntTupleT = (0, 0, 0, 255)
    if contrast_ratio(white, background) >= contrast_ratio(black, background):
        return white
    return black


@dataclass(frozen=True, slots=True)
class ColorScheme(Mapping[str, _4IntTupleT]):
    """一套 MD3 配色: 色彩角色名 (primary / on_surface / surface_container 等) 到 RGBA。

    角色名与 MCU 的 DynamicScheme 属性名一致, 完整列表见 ``roles()``。
    """

    source: _4IntTupleT
    is_dark: bool
    variant: SchemeVariant
    colors: Mapping[str, _4IntTupleT]

    def __getitem__(self, role: str) -> _4IntTupleT:
        return self.colors[role]

    def __iter__(self) -> Iterator[str]:
        return iter(self.colors)

    def __len__(self) -> int:
        return len(self.colors)

    def roles(self) -> list[str]:
        return list(self.colors)


def scheme_from_color(
    source: _ColorTupleT,
    *,
    dark: bool = True,
    variant: SchemeVariant = SchemeVariant.FIDELITY,
    contrast: float = 0.0,
) -> ColorScheme:
    """由源色生成配色。contrast 取 -1 ~ 1, 0 为 MD3 标准对比度。

    结果按 (源色, 变体, 深浅, 对比度) 缓存, 见模块文档里的耗时说明。
    """
    argb = rgba_to_argb(source) | 0xFF000000
    return ColorScheme(
        source=argb_to_rgba(argb),
        is_dark=dark,
        variant=variant,
        colors=_scheme_colors(argb, variant, dark, contrast),
    )


@lru_cache(maxsize=1024)
def _scheme_colors(
    argb: int, variant: SchemeVariant, dark: bool, contrast: float
) -> Mapping[str, _4IntTupleT]:
    # 运行时的 Variant 是 pybind11 整数枚举 (类型桩写成 StrEnum), 只能按成员名取
    mcu_variant = getattr(Variant, variant.name)
    theme = theme_from_argb_color(argb, contrast, mcu_variant)
    scheme = theme.schemes.dark if dark else theme.schemes.light
    # 缓存的结果在调用方之间共享, 包成只读视图
    return MappingProxyType(
        {
            k: _hex_to_rgba(v)
            for k, v in scheme.dict().items()
            if isinstance(v, str) and v.startswith("#")
        }
    )
