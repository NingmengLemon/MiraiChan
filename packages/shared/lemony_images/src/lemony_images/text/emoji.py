"""从彩色字体直接画 emoji 字形。

``ColorFontEmoji`` 把 emoji 簇渲染成 RGBA 图片, 不需要网络, 也不需要贴图。
emoji 簇在排版里占一个字号宽的方块, 具体怎么贴见 ``lemony_images.text.draw``。
"""

import logging
import math
import struct
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

__all__ = ["ColorFontEmoji", "fit_to_square"]

logger = logging.getLogger(__name__)

# 取 .notdef 用的非字符: Unicode 规定 U+FDD0..U+FDEF 永不分配给任何字符
_NOTDEF_PROBE = "\ufdd0"

# 带颜色的字表: 有任意一个就说明这个字体带彩色字形
# (表名读出来时去掉了尾随空格, 所以这里写 SVG 而不是 "SVG ")
_COLOR_TABLE_TAGS = ("COLR", "CBDT", "sbix", "SVG")
# 位图字体的字号表, 位图字体只在这些字号下能打开
_BITMAP_SIZE_TABLE_TAG = "CBLC"
# 矢量彩色字体的主表与版本号位置
_COLOR_LAYER_TABLE_TAG = "COLR"


def _sfnt_offset(path: Path) -> int:
    """字体集合 (.ttc) 里第一个字面的偏移; 普通字体返回 0"""
    with open(path, "rb") as fp:
        header = fp.read(12)
        if header[:4] != b"ttcf":
            return 0
        # ttc 头: tag(4) version(4) numFonts(4) offsetTable[numFonts]
        return struct.unpack(">I", fp.read(4))[0]


def _table_directory(path: Path) -> dict[str, tuple[int, int]]:
    """读 sfnt 表目录, 得到 tag -> (偏移, 长度)"""
    offset = _sfnt_offset(path)
    with open(path, "rb") as fp:
        fp.seek(offset)
        header = fp.read(12)
        if len(header) < 12:
            raise OSError(f"not a valid font file: {path}")
        num_tables = struct.unpack(">H", header[4:6])[0]
        tables: dict[str, tuple[int, int]] = {}
        for _ in range(num_tables):
            record = fp.read(16)
            if len(record) < 16:
                raise OSError(f"truncated font table directory: {path}")
            tag = record[:4].decode("latin-1").strip()
            table_offset, length = struct.unpack(">II", record[8:16])
            tables[tag] = (table_offset, length)
    return tables


def _bitmap_strikes(path: Path, offset: int) -> list[int]:
    """CBLC 里登记的位图字号 (ppem), 升序。

    CBLC 头是 version(4) + numSizes(4), 之后每个 48 字节的 BitmapSizeTable
    在偏移 44 / 45 处是 ppemX / ppemY。
    """
    with open(path, "rb") as fp:
        fp.seek(offset)
        head = fp.read(8)
        if len(head) < 8:
            return []
        num_sizes = struct.unpack(">I", head[4:8])[0]
        strikes = []
        for _ in range(num_sizes):
            record = fp.read(48)
            if len(record) < 48:
                break
            strikes.append(record[44])
    return sorted({size for size in strikes if size > 0})


def _colr_version(path: Path, offset: int) -> int:
    """COLR 表的版本号: 0 是分层矢量 (COLRv0), 1 是 paint graph (COLRv1)"""
    with open(path, "rb") as fp:
        fp.seek(offset)
        head = fp.read(2)
    return struct.unpack(">H", head)[0] if len(head) == 2 else 0


def _scale_to_fit(size: tuple[int, int], target: int) -> tuple[int, int]:
    longest = max(size)
    scale = target / longest
    return max(1, round(size[0] * scale)), max(1, round(size[1] * scale))


def fit_to_square(image: Image.Image, size: int) -> Image.Image:
    """把图片按长边缩到 size, 保持长宽比 (不拉伸); 本来就是这么大时原样返回"""
    image = image.convert("RGBA")
    if max(image.size) == size:
        return image
    return image.resize(_scale_to_fit(image.size, size), Image.Resampling.LANCZOS)


class ColorFontEmoji:
    """用彩色字体把 emoji 簇画成图片。

    位图字体 (CBDT/CBLC, 例如 Debian 的 Noto Color Emoji) 只在自带字号下能打开,
    这时按最接近的字号渲染再缩放; 矢量彩色字体 (COLR/CPAL) 则按需要的字号直接画,
    缩放到最终尺寸时损失更小。

    渲染结果是去掉了透明边距的 RGBA 图片, 交给绘制层按字号缩放。
    """

    def __init__(self, font_file: str | Path, *, cache_size: int = 2048) -> None:
        self._path = Path(font_file)
        self._tables = _table_directory(self._path)
        cblc = self._tables.get(_BITMAP_SIZE_TABLE_TAG)
        self._strikes = _bitmap_strikes(self._path, cblc[0]) if cblc else []
        colr = self._tables.get(_COLOR_LAYER_TABLE_TAG)
        self._colr_version = _colr_version(self._path, colr[0]) if colr else None
        self._cache: OrderedDict[tuple[str, int], Image.Image | None] = OrderedDict()
        self._cache_size = cache_size
        # 各字号下 .notdef 的样子, 用来认"字体里没有这个字形"
        self._notdef: dict[int, Image.Image | None] = {}
        if self.is_color and not self.can_rasterize_color:
            logger.warning(
                "emoji 字体 %s 是 COLRv1/SVG 彩色字体, Pillow 画不出这类字形, "
                "请换 COLRv0 或 CBDT/sbix 的字体",
                self._path,
            )

    @property
    def colr_version(self) -> int | None:
        """COLR 表版本; 没有 COLR 表时是 None"""
        return self._colr_version

    @property
    def is_color(self) -> bool:
        """字体是否带彩色表; 不带的话画出来只有轮廓色, 应改用别的来源"""
        return any(tag in self._tables for tag in _COLOR_TABLE_TAGS)

    @property
    def can_rasterize_color(self) -> bool:
        """Pillow 能否把彩色字形画出来。

        CBDT/CBLC 与 sbix 是位图表, COLRv0 是分层矢量表, Pillow 都支持;
        COLRv1 与 SVG 表要靠 paint graph / SVG 渲染, Pillow 没接, 这类字体
        的 emoji 字形在 ``render`` 里一律返回 None。
        """
        if _BITMAP_SIZE_TABLE_TAG in self._tables or "sbix" in self._tables:
            return True
        return self._colr_version == 0

    def render(self, cluster: str, *, target: int = 160) -> Image.Image | None:
        """画出一个 emoji 簇; 字体里没有对应字形时返回 None"""
        key = (cluster, target)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        image = self._render(cluster, target)
        self._cache[key] = image
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return image

    def clear(self) -> None:
        self._cache.clear()
        self._notdef.clear()

    def _render_size(self, want: int) -> int:
        if not self._strikes:
            return want
        bigger = [size for size in self._strikes if size >= want]
        return min(bigger) if bigger else max(self._strikes)

    def _render(self, cluster: str, target: int) -> Image.Image | None:
        size = self._render_size(max(target, 16))
        image = self._paint(cluster, size)
        # 字体里没有这个字形时画出来的就是 .notdef (方框), 要当成"没有"而不是一张图;
        # 否则调用方永远等不到 None, "字体里没有就走下一级来源"的兜底就成了摆设
        if image is None or _same_image(image, self._notdef_image(size)):
            return None
        if max(image.size) > target:
            image = image.resize(
                _scale_to_fit(image.size, target), Image.Resampling.LANCZOS
            )
        return image

    def _notdef_image(self, size: int) -> Image.Image | None:
        """该字号下 .notdef 的墨迹, 用非字符取 (Unicode 保证非字符永不分配)"""
        if size not in self._notdef:
            self._notdef[size] = self._paint(_NOTDEF_PROBE, size)
        return self._notdef[size]

    def _paint(
        self, cluster: str, size: int, *, attempt: int = 0
    ) -> Image.Image | None:
        """把簇画到画布上再裁到墨迹; 字体里没有字形时会得到 .notdef 的样子。

        画布按簇的实际 advance 定宽: 未成合字的 ZWJ 序列 (旧字体常见) 会占
        好几个字号的宽度, 按字号方块开画布会把它切掉。墨迹顶到画布右边或下边
        说明还是估小了, 放大一倍重画一次。
        """
        font = ImageFont.truetype(str(self._path), size)
        # 字形可能带负的 bearing, 留出边距并把原点往右下挪, 画完再裁到墨迹
        pad = max(4, size // 3)
        advance = font.getlength(cluster)
        ink = font.getbbox(cluster)
        scale = 2**attempt
        width = math.ceil(max(advance, ink[2] - ink[0], size)) * scale + 2 * pad
        height = math.ceil(max(ink[3], sum(font.getmetrics()), size)) * scale + 2 * pad
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text(
            (pad - min(0, ink[0]), pad - min(0, ink[1])),
            cluster,
            font=font,
            fill=(0, 0, 0, 255),
            embedded_color=True,
        )
        box = canvas.getbbox()
        if box is None:
            return None
        if (box[2] >= width or box[3] >= height) and attempt < 1:
            retried = self._paint(cluster, size, attempt=attempt + 1)
            if retried is not None:
                return retried
        return canvas.crop(box)


def _same_image(a: Image.Image | None, b: Image.Image | None) -> bool:
    """两张图是否像素级相同 (Pillow 的 Image 没有像素相等的 ==)"""
    if a is None or b is None:
        return a is b
    return a.size == b.size and a.tobytes() == b.tobytes()
