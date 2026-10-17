"""在感知均匀的色彩空间里混色与调明暗 (基于 coloraide)。

直接在 sRGB 里线性插值会让中间色发灰、发暗; 这里默认用 OKLab / OKLCh,
结果超出 sRGB 色域时按 coloraide 的默认方法压回色域。alpha 按线性插值处理。
"""

from coloraide import Color

from ..typedef import _4IntTupleT, _ColorTupleT

__all__ = ["darken", "lighten", "mix"]


def _to_color(c: _ColorTupleT) -> Color:
    return Color("srgb", [c[0] / 255, c[1] / 255, c[2] / 255])


def _to_rgba(c: Color, alpha: int) -> _4IntTupleT:
    srgb = c.convert("srgb").fit("srgb")
    r, g, b = (max(0, min(255, round(v * 255))) for v in srgb.coords())
    return (r, g, b, alpha)


def _alpha(c: _ColorTupleT) -> int:
    return c[3] if len(c) == 4 else 255


def mix(
    a: _ColorTupleT, b: _ColorTupleT, t: float, *, space: str = "oklab"
) -> _4IntTupleT:
    """从 a 向 b 混合, t=0 为 a, t=1 为 b; space 取 coloraide 的空间名 (oklab / oklch / srgb ...)"""
    if not 0 <= t <= 1:
        raise ValueError(f"t out of range: {t}")
    mixed = _to_color(a).mix(_to_color(b), t, space=space)
    alpha = round(_alpha(a) + (_alpha(b) - _alpha(a)) * t)
    return _to_rgba(mixed, alpha)


def _shift_lightness(c: _ColorTupleT, delta: float) -> _4IntTupleT:
    lch = _to_color(c).convert("oklch")
    lch["lightness"] = max(0.0, min(1.0, lch["lightness"] + delta))
    return _to_rgba(lch, _alpha(c))


def lighten(c: _ColorTupleT, amount: float) -> _4IntTupleT:
    """OKLCh 明度加 amount (0 ~ 1), 色相不变"""
    return _shift_lightness(c, amount)


def darken(c: _ColorTupleT, amount: float) -> _4IntTupleT:
    """OKLCh 明度减 amount (0 ~ 1), 色相不变"""
    return _shift_lightness(c, -amount)
