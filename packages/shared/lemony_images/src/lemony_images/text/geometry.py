"""画布与排版的几何计算。"""

from PIL import Image, ImageDraw

from ..typedef import _BboxT

__all__ = ["calc_bbox", "image_of"]


def image_of(draw: ImageDraw.ImageDraw) -> Image.Image:
    """取 draw 底下的 Image。

    Pillow 没给公开访问器: ``draw.im`` 是 ImagingCore 而不是 Image, ``draw._image``
    才是。集中在这里一处, Pillow 以后变了只改这里。
    """
    return draw._image


def calc_bbox(
    actual_bbox: _BboxT,
    expected_bbox: _BboxT,
    sticky: str | None = None,
) -> tuple[int, int]:
    """算小 bbox 左上角该落在哪, 让它摆在大 bbox 里。

    - 小 bbox: 真正要画的东西占的范围
    - 大 bbox: 目标区域
    - sticky: 参考 tkinter 的 grid 布局里的 sticky, ``None`` 时横纵居中;
      ``n`` / ``s`` / ``w`` / ``e`` 及组合把对应方向贴边
    """
    aw, ah = actual_bbox[2] - actual_bbox[0], actual_bbox[3] - actual_bbox[1]
    ew, eh = expected_bbox[2] - expected_bbox[0], expected_bbox[3] - expected_bbox[1]
    x, y = (
        expected_bbox[0] + (ew - aw) / 2,
        expected_bbox[1] + (eh - ah) / 2,
    )  # 初始居中
    if sticky:
        for s in sticky:
            match s:
                case "w":
                    x = expected_bbox[0]
                case "s":
                    y = expected_bbox[1] + eh - ah
                case "e":
                    x = expected_bbox[0] + ew - aw
                case "n":
                    y = expected_bbox[1]
    return int(x), int(y)
