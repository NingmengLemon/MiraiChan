"""从图片里取颜色的简单方法。按 MD3 评分取源色见 ``dynamic.source_color``。"""

import numpy as np
from PIL import Image, ImageFilter

from ..typedef import _4IntTupleT

__all__ = ["average_color", "get_main_color"]


def get_main_color(image: Image.Image, radius: float | None = None, resize: int = 10):
    """通过 缩小图像 + 高斯模糊 + 取中心点颜色 取得主要颜色

    取的是画面中心附近的颜色, 不是整张图的主题色。

    Inspired by Moncak

    ~~没错插件 `EroMoncak` 的名字里的 `Moncak` 就是这只萝莉~~"""
    blurred = image.resize((resize, resize)).filter(
        ImageFilter.GaussianBlur(resize if radius is None else radius)
    )
    w, h = blurred.size
    return blurred.getpixel((w // 2, h // 2))


def average_color(image: Image.Image) -> _4IntTupleT | None:
    """不透明像素的平均色 (按 alpha 加权); 图片全透明时返回 None"""
    rgba = image.convert("RGBA")
    rgba.thumbnail((128, 128))
    px = np.asarray(rgba, dtype=np.float64).reshape(-1, 4)
    weight = px[:, 3].sum()
    if weight == 0:
        return None
    r, g, b = (px[:, :3] * px[:, 3:4]).sum(axis=0) / weight
    return (round(r), round(g), round(b), 255)
