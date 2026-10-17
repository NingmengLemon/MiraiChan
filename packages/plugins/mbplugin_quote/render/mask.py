"""卡片遮罩: 按参数画出来, 不占用图片资源。

遮罩左侧全透明、右侧全不透明, 中间是一条斜向渐变带: 渐变从顶边的 ``fade_from``
开始, 宽 ``fade_width``, 底边整体右移 ``slant``, 过渡曲线由 ``curve`` 在直线与
smoothstep 之间插值。三个长度都是卡片宽度的比例, 换卡片尺寸不用改参数。

画法是一条横向渐变条, 再用仿射变换按行取不同偏移量做剪切, 斜向渐变就出来了。
默认参数算出来的位置 (卡宽 1920 时) 是顶边 217px 起、宽 493px、倾斜 367px, 位置与
曲线形状由 `test_mask.py` 的几何断言钉住; 与卡片现行那张图逐像素比最大差 2/255
(均值 0.16), 这个数字记录在引入它的提交信息里。
"""

from dataclasses import dataclass
from math import ceil

from PIL import Image

__all__ = ["MaskCache", "MaskStyle", "build_mask"]

Size = tuple[int, int]


@dataclass(frozen=True, slots=True)
class MaskStyle:
    """遮罩参数; 取值域与 ``settings.MaskSettings`` 一致。

    ``fade_from`` 与 ``curve`` 在 [0, 1], ``fade_width`` 大于 0, ``slant`` 在 [-1, 1]。
    这里不做校验: 插件侧的配置模型负责拒绝越界值, 直接构造时越界的参数由
    ``build_mask`` 的夹取与 ``span`` 下限兜住。
    """

    fade_from: float = 0.113
    fade_width: float = 0.257
    slant: float = 0.191
    curve: float = 0.5


def _ease(t: float, curve: float) -> float:
    """0 是直线, 1 是 smoothstep (两端平缓, 中间更陡)"""
    return t + curve * (t * t * (3.0 - 2.0 * t) - t)


_DEFAULT_STYLE = MaskStyle()


def build_mask(size: Size, style: MaskStyle = _DEFAULT_STYLE) -> Image.Image:
    """画一张 ``size`` 大小的 alpha 遮罩 ("L" 模式), 尺寸通常就是卡片尺寸。"""
    w, h = size
    span = max(style.fade_width * w, 1.0)
    slant = style.slant * w
    curve = min(max(style.curve, 0.0), 1.0)
    # 第 y 行的渐变起点是 fade_from*w + slant*y/h, 底边相对顶边偏移 edge
    edge = slant * (h - 1) / h
    shift = max(edge, 0.0)
    base_w = ceil(w + abs(edge) + shift) + 2
    ramp0 = style.fade_from * w + shift
    row = bytes(
        round(255.0 * _ease(min(max((i - ramp0) / span, 0.0), 1.0), curve))
        for i in range(base_w)
    )
    # 两行完全相同, 剪切时落在行中心, 横向才是唯一的变量
    base = Image.frombytes("L", (base_w, 1), row).resize(
        (base_w, 2), Image.Resampling.NEAREST
    )
    # 仿射变换把输出像素中心映射到输入: 采样点是 a*(x+1/2) + b*(y+1/2) + c - 1/2,
    # 半像素的剪切量要补进常数项, 否则每行的渐变会整体偏 0.5*slant/h 个像素
    return base.transform(
        size,
        Image.Transform.AFFINE,
        (1.0, -slant / h, shift + slant / (2 * h), 0.0, 0.0, 0.5),
        Image.Resampling.BILINEAR,
    )


class MaskCache:
    """按 (尺寸, 参数) 缓存遮罩: 参数没变就复用, 变了才重画。

    插件在启动时画一次; 参数来自配置, 改了配置要重启才生效。以后接上配置热重载时,
    换成新的 ``MaskStyle`` 再调 ``get`` 就会重画, 不用另外通知。

    返回的图是共享的, 调用方不要就地修改。
    """

    __slots__ = ("_image", "_key")

    def __init__(self) -> None:
        self._key: tuple[Size, MaskStyle] | None = None
        self._image: Image.Image | None = None

    def get(self, size: Size, style: MaskStyle) -> Image.Image:
        key = (size, style)
        if self._image is None or key != self._key:
            self._image = build_mask(size, style)
            self._key = key
        return self._image
