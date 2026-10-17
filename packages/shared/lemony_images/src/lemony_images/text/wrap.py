"""断行与字号拟合。

测量全部走 ``lemony_images.text.metrics``: 一行有多高、emoji 簇占多宽只在那里
定义一次, 绘制层用同一套数值。拟合用的块高也来自那里 (``block_height``), 所以
"算出来放得下"与"画出来放得下"是同一件事。

断行按排版单元找"可断点", 不在词中间断:

- 西文与数字连成的整块当一个不可断的单元, 只在空白之后断开
- 汉字、假名、谚文之间随处可断, 但要遵守行首禁则与行尾禁则
- emoji 簇 (含 ZWJ 序列) 在 ``emoji_as_square=True`` 时整体不断开

宽度用真实前缀测量 (``font.getlength``), 与最终画出来的那一行是同一个数, 所以
断行判断和绘制不会因为 kerning 分叉。单个单元比整行还宽 (长路径、URL) 时才退到
单元级硬断; 硬断之后仍会用单元边界把这一行填满, 不留大片空白。

软断行落在空白处时, 断点两侧的空白都不保留 (落在断点上的缩进也会被吃掉)。
"""

import bisect
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from PIL import ImageFont

from .font import FontCache
from .metrics import (
    block_height,
    emoji_square_width,
    line_height,
    line_width,
    split_clusters,
)

__all__ = [
    "calc_font_size",
    "measure_lines",
    "wrap_text_by_length",
    "wrap_text_by_width",
]

# 行首禁则: 这些字符不放在行首, 断点不能落在它们前面
_NO_LINE_START = frozenset(
    "。，、；：？！）」』】》〉〕｝"  # 全角收尾标点
    "!?;:)]}"  # 半角收尾; 不含 . 与 , 免得把 3.5 这种数拆开
)
# 行尾禁则: 这些字符不放在行尾, 断点不能落在它们后面
_NO_LINE_END = frozenset("（「『【《〈〔｛([{")
# 两侧都不许断: 破折号、省略号连排时不拆, 不换行空格是真不许断
_NO_BREAK_AROUND = frozenset("—―…\u00a0")


def _is_cjk(ch: str) -> bool:
    """汉字、假名、谚文、全角符号: 这些字符之间可以逐字断行"""
    o = ord(ch)
    return (
        0x2E80 <= o <= 0x2FFF  # 部首
        or 0x3000 <= o <= 0x303F  # 中文标点
        or 0x3040 <= o <= 0x30FF  # 假名
        or 0x3130 <= o <= 0x318F  # 谚文字母
        or 0x3400 <= o <= 0x4DBF  # 扩展 A
        or 0x4E00 <= o <= 0x9FFF  # 基本区
        or 0xA960 <= o <= 0xA97F
        or 0xAC00 <= o <= 0xD7AF  # 谚文音节
        or 0xF900 <= o <= 0xFAFF  # 兼容汉字
        or 0xFE10 <= o <= 0xFE1F  # 竖排标点
        or 0xFE30 <= o <= 0xFE4F  # 兼容标点
        or 0xFF00 <= o <= 0xFFEF  # 全角
        or 0x20000 <= o <= 0x3FFFF  # 扩展 B 以后
    )


# 组合字符之外还有零宽连接符与变体选择符, 它们也贴在前一个字符上
_ATTACHING_CATEGORIES = frozenset({"Mn", "Me"})


def _attaches(ch: str) -> bool:
    """这个字符贴在前一个字符上, 断在它前面会把字形拆坏"""
    return (
        ch == "\u200d"
        or unicodedata.combining(ch) != 0
        or unicodedata.category(ch) in _ATTACHING_CATEGORIES
    )


def _can_break(prev: str, nxt: str) -> bool:
    """两个字符之间能不能断行"""
    if prev in _NO_BREAK_AROUND or nxt in _NO_BREAK_AROUND:
        return False
    if nxt in _NO_LINE_START:
        return False
    if prev in _NO_LINE_END:
        return False
    if prev.isspace():
        return True
    if prev in _NO_LINE_START:
        return True
    return _is_cjk(prev) or _is_cjk(nxt)


@dataclass(frozen=True, slots=True)
class _Layout:
    """一行文本的断点与测量方式

    ``soft_ends`` 是允许断行的位置 (可直接断), ``hard_ends`` 是可能断开的全部位置
    (单元边界, 只在单元超宽时用到), 都以字符下标表示, 且都包含行尾。
    """

    soft_ends: list[int]
    hard_ends: list[int]
    measure: Callable[[int, int], float]


def _plain_layout(line: str, font: ImageFont.FreeTypeFont) -> _Layout:
    """纯文本: 每个码位一个单元, 宽度用真实前缀测量"""
    n = len(line)
    hard = [i for i in range(1, n) if not _attaches(line[i])]
    hard.append(n)
    soft = [i for i in hard if i == n or _can_break(line[i - 1], line[i])]
    return _Layout(soft, hard, lambda a, b: font.getlength(line[a:b]))


def _emoji_layout(line: str, font: ImageFont.FreeTypeFont) -> _Layout:
    """emoji 模式: 簇内不断, 簇外按纯文本规则, 宽度按字号方块加文字实测"""
    n = len(line)
    size = emoji_square_width(font)
    plain_chars: list[str] = []
    plain_before = [0] * (n + 1)
    emoji_before = [0] * (n + 1)
    inside_emoji = [False] * (n + 1)
    cluster_starts: set[int] = set()
    cluster_ends: set[int] = set()
    pos = 0
    for chunk, is_emoji in split_clusters(line):
        end = pos + len(chunk)
        for k, ch in enumerate(chunk):
            plain_before[pos + k + 1] = plain_before[pos + k] + (0 if is_emoji else 1)
            emoji_before[pos + k + 1] = emoji_before[pos + k]
            if not is_emoji:
                plain_chars.append(ch)
        if is_emoji:
            # 簇内只有首尾能断, 中间这些位置不能
            for k in range(pos + 1, end):
                inside_emoji[k] = True
            emoji_before[end] = emoji_before[pos] + 1
            cluster_starts.add(pos)
            cluster_ends.add(end)
        pos = end
    plain_text = "".join(plain_chars)

    def measure(a: int, b: int) -> float:
        return (
            font.getlength(plain_text[plain_before[a] : plain_before[b]])
            + (emoji_before[b] - emoji_before[a]) * size
        )

    hard = [i for i in range(1, n) if not inside_emoji[i] and not _attaches(line[i])]
    hard.append(n)
    soft = [
        i
        for i in hard
        if i == n
        or i in cluster_ends
        or i in cluster_starts
        or _can_break(line[i - 1], line[i])
    ]
    return _Layout(soft, hard, measure)


def _fill(
    start: int,
    floor: int,
    ceiling: int,
    hard: list[int],
    measure: Callable[[int, int], float],
    limit: float,
) -> int:
    """在 ``floor`` 到 ``ceiling`` 之间的单元边界里找最远的、放得下的位置

    找不到比 ``floor`` 更远的就原样返回 ``floor``: 这一步只负责"还能不能再塞",
    不负责保证前进, 前进由调用方保证。
    """
    lo = bisect.bisect_right(hard, floor)
    hi = bisect.bisect_right(hard, ceiling) - 1
    best = floor
    while lo <= hi:
        mid = (lo + hi) // 2
        if measure(start, hard[mid]) <= limit:
            best = hard[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _find_cut(
    start: int,
    n: int,
    soft: list[int],
    hard: list[int],
    measure: Callable[[int, int], float],
    limit: float,
) -> int:
    """本行最远能放到哪里; 结果总大于 ``start``, 保证断行循环一定前进"""
    first = bisect.bisect_right(soft, start)
    if first >= len(soft):
        return n
    last = len(soft) - 1
    # 指数探测找一个放得下的可断点和一个放不下的, 再二分收尾
    fit = -1
    idx = first
    step = 1
    while idx <= last:
        if measure(start, soft[idx]) > limit:
            break
        fit = idx
        if idx == last:
            return n
        idx = min(idx + step, last)
        step *= 2
    if fit < 0:
        # 第一个可断点就放不下: 这个单元自己比整行还宽, 退到单元级硬断
        cut = _fill(start, start, soft[first], hard, measure, limit)
        if cut > start:
            return cut
        # 一个单元都放不下, 也要让它单独占一行, 否则断行循环原地打转
        j = bisect.bisect_right(hard, start)
        return hard[j] if j < len(hard) else soft[first]
    lo, hi = fit, idx
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if measure(start, soft[mid]) <= limit:
            lo = mid
        else:
            hi = mid
    # 只有"下一个词自己就比整行宽"时才在它内部硬断; 否则整词挪到下一行, 不劈开词
    if measure(soft[lo], soft[hi]) > limit:
        return _fill(start, soft[lo], soft[hi], hard, measure, limit)
    return soft[lo]


def _wrap_line(line: str, limit: float, layout: _Layout) -> list[str]:
    """把一行按宽度切开; 软断点两侧的空白会被吃掉"""
    n = len(line)
    out: list[str] = []
    start = 0
    while start < n:
        cut = _find_cut(
            start, n, layout.soft_ends, layout.hard_ends, layout.measure, limit
        )
        piece = line[start:cut]
        if cut < n:
            # 软换行落点是空白时, 两侧的空白都是排版噪音, 不画
            piece = piece.rstrip()
            while cut < n and line[cut].isspace():
                cut += 1
            start = cut
            if piece:
                out.append(piece)
            continue
        out.append(piece)
        start = cut
    return out or [""]


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
    """根据像素宽度断行, 尽量不在词中间断开

    emoji_as_square=True 时 emoji 簇占一个字号宽的方块, 并且整体不拆开; 否则
    按字体实测, 与 ``metrics.unit_width`` 的约定一致。

    断点规则: 西文词与数字整体不拆, 只在空白后断; 汉字等 CJK 字符之间随处可断,
    并遵守行首禁则 (收尾标点不放行首) 与行尾禁则 (起首标点不放行尾)。单元自己
    比整行还宽时 (长路径、URL) 才硬断。软断行处的空白不保留。
    """
    result: list[str] = []
    limit = int(line_width_limit)
    # 按 \n 切而不是 splitlines(): 尾随空行要保住, 否则绘制层会少算一行
    for raw in s.split("\n"):
        # CRLF 的 \r 不算换行, 留着会被当成要量的字符
        line = raw[:-1] if raw.endswith("\r") else raw
        if not line:
            result.append("")
            continue
        layout = (
            _emoji_layout(line, font) if emoji_as_square else _plain_layout(line, font)
        )
        result.extend(_wrap_line(line, limit, layout))
    return result


def measure_lines(
    text: str, font: ImageFont.FreeTypeFont, *, emoji_as_square: bool
) -> list[float]:
    """多行文本每行的宽度"""
    return [
        line_width(line, font, emoji_as_square=emoji_as_square)
        for line in text.split("\n")
    ]


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
    高度用 ``metrics.block_height``, 与绘制层同一个定义, 不多算一个 spacing。
    """
    # 上限比下限小时按上下限相等处理, 否则会返回一个比 max_font_size 还大的字号
    max_font_size = max(max_font_size, min_font_size)
    for fsize in range(max_font_size, min_font_size, -1):
        font = fontcache.use(fsize)
        lines = wrap_text_by_width(
            text, box_width, font, emoji_as_square=emoji_as_square
        )
        if block_height(len(lines), line_height(font), spacing) <= box_height:
            return fsize, "\n".join(lines)
    font = fontcache.use(min_font_size)
    lines = wrap_text_by_width(text, box_width, font, emoji_as_square=emoji_as_square)
    return min_font_size, "\n".join(lines)
