"""颜色表示之间的转换: 各种写法 -> RGBA 四元组, RGBA <-> ARGB 整数 / hex。"""

from typing import Any

from ..typedef import _4IntTupleT, _ColorT, _ColorTupleT

__all__ = [
    "argb_to_rgba",
    "ensure_4inttuple",
    "ensure_4inttuple_color",
    "rgba_to_argb",
    "to_hex",
    "with_alpha",
]


def ensure_4inttuple(obj: tuple[Any, Any, Any, Any]) -> _4IntTupleT:
    return (int(obj[0]), int(obj[1]), int(obj[2]), int(obj[3]))


def ensure_4inttuple_color(
    color: _ColorT
    | tuple[float | int, float | int, float | int, float | int]
    | tuple[float | int, float | int, float | int],  # 兼容不规范的输入
) -> _4IntTupleT:
    """确保颜色是 RGBA 四元组形式。

    int: 不超过 0xFFFFFF 时按 RGB, 否则按 RGBA; str: ``#RRGGBB`` 或 ``#RRGGBBAA``。
    """
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
    if isinstance(color, str):
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
    if isinstance(color, tuple):
        if len(color) == 3:
            r, g, b = color
            a = 255
        elif len(color) == 4:
            r, g, b, a = color
        else:
            raise ValueError(f"Invalid color tuple: {color}")
        return ensure_4inttuple((r, g, b, a))
    raise TypeError(f"Unsupported color type: {type(color)}")


def argb_to_rgba(argb: int) -> _4IntTupleT:
    """MCU 等库使用的 0xAARRGGBB 整数 -> RGBA"""
    return ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF, (argb >> 24) & 0xFF)


def rgba_to_argb(color: _ColorTupleT) -> int:
    a = color[3] if len(color) == 4 else 255
    return (a << 24) | (color[0] << 16) | (color[1] << 8) | color[2]


def to_hex(color: _ColorTupleT, *, alpha: bool = False) -> str:
    """``#rrggbb``; alpha=True 时为 ``#rrggbbaa``"""
    r, g, b, a = ensure_4inttuple_color(color)
    return f"#{r:02x}{g:02x}{b:02x}" + (f"{a:02x}" if alpha else "")


def with_alpha(color: _ColorTupleT, alpha: int) -> _4IntTupleT:
    if not 0 <= alpha <= 255:
        raise ValueError(f"alpha out of range: {alpha}")
    return (color[0], color[1], color[2], alpha)
