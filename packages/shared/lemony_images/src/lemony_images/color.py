from typing import Any

from PIL import Image, ImageFilter

from .typedef import _4IntTupleT, _ColorT, _ColorTupleT


def ensure_4inttuple(obj: tuple[Any, Any, Any, Any]) -> _4IntTupleT:
    return (int(obj[0]), int(obj[1]), int(obj[2]), int(obj[3]))


def ensure_4inttuple_color(
    color: _ColorT
    | tuple[float | int, float | int, float | int, float | int]
    | tuple[float | int, float | int, float | int],  # 兼容不规范的输入
) -> _4IntTupleT:
    """确保颜色是 RGBA 四元组形式"""
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
    elif isinstance(color, str):
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
    elif isinstance(color, tuple):
        if len(color) == 3:
            r, g, b = color
            a = 255
        elif len(color) == 4:
            r, g, b, a = color
        else:
            raise ValueError(f"Invalid color tuple: {color}")
        return ensure_4inttuple((r, g, b, a))
    else:
        raise TypeError(f"Unsupported color type: {type(color)}")


def rel_lumin(color: _ColorTupleT) -> float:
    """相对亮度"""

    def conv(x: float):
        x = x / 255.0
        return (x / 12.92) if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = map(conv, color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color1: _ColorTupleT, color2: _ColorTupleT):
    """对比度"""
    l1 = rel_lumin(color1)
    l2 = rel_lumin(color2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def get_main_color(image: Image.Image, radius: None | float = None, resize: int = 10):
    """通过 缩小图像 + 高斯模糊 + 取中心点颜色 取得主要颜色

    Inspired by Moncak

    ~~没错插件 `EroMoncak` 的名字里的 `Moncak` 就是这只萝莉~~"""
    blurred = image.resize((resize, resize)).filter(
        ImageFilter.GaussianBlur(resize if radius is None else radius)
    )
    w, h = blurred.size
    return blurred.getpixel((w // 2, h // 2))
