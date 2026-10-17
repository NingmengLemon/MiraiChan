"""断行与字号拟合。

这里的测量全部走 ``lemony_images.text.metrics``: 一行有多高、emoji 簇占多宽都只在
那里定义一次, 绘制层用同一套数值, 所以"算出来放得下"与"画出来放得下"是一回事。
"""

from PIL import ImageFont

from .font import FontCache
from .metrics import line_height, line_width, split_clusters, unit_width

__all__ = ["calc_font_size", "wrap_text_by_length", "wrap_text_by_width"]


def wrap_text_by_length(s: str, line_length: int) -> list[str]:
    """根据字符长度断行"""
    result: list[str] = []
    for line in s.splitlines():
        result.extend(
            line[i : i + line_length] for i in range(0, len(line), line_length)
        )
    return result


def wrap_text_by_width(
    s: str,
    line_width_limit: float,
    font: ImageFont.FreeTypeFont,
    *,
    emoji_as_square: bool = False,
) -> list[str]:
    """根据像素宽度断行

    emoji_as_square=True 时 emoji 簇占一个字号宽的方块, 并且整体不拆开。
    """
    result: list[str] = []
    limit = int(line_width_limit)
    for line in s.splitlines():
        if not line:
            result.append("")
            continue
        if emoji_as_square:
            units = [
                (chunk, unit_width(chunk, is_emoji, font, emoji_as_square=True))
                for chunk, is_emoji in split_clusters(line)
            ]
        else:
            units = [(c, font.getlength(c)) for c in line]
        current: list[str] = []
        current_width = 0.0
        for chunk, width in units:
            # 单个单元比整行还宽时也会被放到新起的一行, 不会原地打转
            if current and current_width + width > limit:
                result.append("".join(current))
                current = []
                current_width = 0.0
            current.append(chunk)
            current_width += width
        if current:
            result.append("".join(current))
    return result


def calc_font_size(
    text: str,
    max_font_size: int,
    box_width: int,
    box_height: int,
    fontcache: FontCache,
    min_font_size: int = 20,
    spacing: int = 4,
    *,
    emoji_as_square: bool = False,
) -> tuple[int, str]:
    """算出能塞进 bbox 的最大字号, 返回字号和断行后的文本

    到最小字号还塞不下时返回最小字号, 此时按返回的字号绘制会超出 bbox 高度。
    高度用的是 ``metrics.line_height``, 与绘制层同一个定义。
    """
    fsize = max_font_size
    while fsize > min_font_size:
        font = fontcache.use(fsize)
        lines = wrap_text_by_width(
            text, box_width, font, emoji_as_square=emoji_as_square
        )
        if (line_height(font) + spacing) * len(lines) <= box_height:
            break
        fsize -= 1
    return fsize, "\n".join(
        wrap_text_by_width(
            text, box_width, fontcache.use(fsize), emoji_as_square=emoji_as_square
        )
    )


def measure_lines(
    text: str, font: ImageFont.FreeTypeFont, *, emoji_as_square: bool = False
) -> list[float]:
    """多行文本每行的宽度"""
    return [
        line_width(line, font, emoji_as_square=emoji_as_square)
        for line in text.split("\n")
    ]
