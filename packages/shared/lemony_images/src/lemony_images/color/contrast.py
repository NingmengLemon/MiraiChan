"""WCAG 2 相对亮度与对比度。"""

from ..typedef import _4IntTupleT, _ColorTupleT

__all__ = ["contrast_ratio", "readable_on", "rel_lumin"]

WHITE: _4IntTupleT = (255, 255, 255, 255)
BLACK: _4IntTupleT = (0, 0, 0, 255)


def rel_lumin(color: _ColorTupleT) -> float:
    """相对亮度, 0 (黑) ~ 1 (白); 忽略 alpha"""

    def conv(x: float):
        x = x / 255.0
        return (x / 12.92) if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = map(conv, color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color1: _ColorTupleT, color2: _ColorTupleT) -> float:
    """对比度, 1 ~ 21; 正文一般要求不低于 4.5, 大字不低于 3"""
    l1 = rel_lumin(color1)
    l2 = rel_lumin(color2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def readable_on(background: _ColorTupleT) -> _4IntTupleT:
    """背景上对比度更高的黑或白"""
    if contrast_ratio(WHITE, background) >= contrast_ratio(BLACK, background):
        return WHITE
    return BLACK
