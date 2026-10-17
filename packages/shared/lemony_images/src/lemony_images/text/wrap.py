"""断行与字号拟合。

测量全部走 ``lemony_images.text.metrics``: 一行有多高、emoji 簇占多宽只在那里
定义一次, 绘制层用同一套数值。拟合用的块高也来自那里 (``block_height``), 所以
"算出来放得下"与"画出来放得下"是同一件事。

断行按排版单元找"可断点", 不在词中间断:

- 西文与数字连成的整块当一个不可断的单元, 只在空白之后断开
- 汉字、假名、谚文之间随处可断, 但要遵守行首禁则与行尾禁则
- emoji 簇 (含 ZWJ 序列) 在 ``emoji_as_square=True`` 时整体不断开

候选行用"将要画出来的那个串"来量: 纯文本走真实前缀测量 (``font.getlength``),
emoji 模式逐簇求和 (与 ``metrics.line_width`` 同一个规则), 行尾不画的空白先剥掉。
于是断行判断的宽度就是绘制层拿到的宽度, 不会因为 kerning 分叉。

单个单元比整行还宽 (长路径、URL) 时才退到单元级硬断; 硬断之后仍会用单元边界把
这一行填满, 不留大片空白。

行尾的空白一律不保留 (整行都是空白时退化成空行), 软断行的下一行也不以空白开头。
一行的宽度只由看得见的像素决定, 尾随空格不会把画布撑宽。
"""

import bisect
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from PIL import ImageFont

from .font import FontCache
from .metrics import (
    block_height,
    line_height,
    line_width,
    split_clusters,
    unit_width,
)

__all__ = [
    "calc_font_size",
    "measure_lines",
    "wrap_text_by_length",
    "wrap_text_by_width",
]

# 行首禁则: 这些字符不放在行首, 断点不能落在它们前面
# 全角收尾标点与日文符号: 它们之后处处可断 (CJK 本来就没有空格), 但它们自己不放行首
_CJK_CLOSERS = frozenset(
    "。，、；：？！）」』】》〉〕｝｣”’"  # 全角收尾标点与弯引号
    "ー々ゝゞヽヾ"  # 日文长音与叠字
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ"  # 小写假名
)
# 半角收尾标点: 同样不放行首, 但不断在它们后面。
# 一断就会把 "12:30" 和 "https://..." 拆开; 西文里断点本来就落在空格上。
_ASCII_CLOSERS = frozenset("!?;:)]}")
# 行首禁则: 这些字符不放行首, 断点不能落在它们前面
_NO_LINE_START = _CJK_CLOSERS | _ASCII_CLOSERS
# 行尾禁则: 这些字符不放行尾, 断点不能落在它们后面
_NO_LINE_END = frozenset("（「『【《〈〔｛｢“‘([{")
# 两侧都不许断: 破折号、省略号连排时不拆, 不换行空格是真不许断
_NO_BREAK_AROUND = frozenset("—―…\u00a0")

# 组合附标 (Mn/Me) 贴在基字上; 零宽连接符与变体选择符分别在 _attaches 里判断
_ATTACHING_CATEGORIES = frozenset({"Mn", "Me"})


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
        or 0xD7B0 <= o <= 0xD7FF  # 谚文字母扩展 B
        or 0xF900 <= o <= 0xFAFF  # 兼容汉字
        or 0xFE10 <= o <= 0xFE1F  # 竖排标点
        or 0xFE30 <= o <= 0xFE4F  # 兼容标点
        or 0xFF00 <= o <= 0xFFEF  # 全角
        or 0x1B000 <= o <= 0x1B16F  # 假名补充、扩展 A 与小写假名扩展
        or 0x20000 <= o <= 0x3FFFF  # 扩展 B 以后
    )


def _attaches(ch: str) -> bool:
    """这个字符贴在前一个字符上, 断在它前面会把字形拆坏"""
    return (
        ch == "\u200d"
        or unicodedata.combining(ch) != 0
        or unicodedata.category(ch) in _ATTACHING_CATEGORIES
    )


def _kinsoku_ok(prev: str, nxt: str) -> bool:
    """禁则: 这个位置允许断开吗 (不看两侧能不能组成词)"""
    if prev in _NO_BREAK_AROUND or nxt in _NO_BREAK_AROUND:
        return False
    if nxt in _NO_LINE_START:
        return False
    return prev not in _NO_LINE_END


def _can_break(prev: str, nxt: str) -> bool:
    """两个字符之间能不能断行"""
    if not _kinsoku_ok(prev, nxt):
        return False
    if prev.isspace() or prev in _CJK_CLOSERS:
        return True
    return _is_cjk(prev) or _is_cjk(nxt)


@dataclass(frozen=True, slots=True)
class _Layout:
    """一行文本的断点与测量方式

    ``soft_ends`` 是允许断行的位置 (可直接断), ``hard_ends`` 是可能断开的全部位置
    (单元边界, 只在单元超宽时用到), 都以字符下标表示, 最后一个元素都是行尾。
    """

    soft_ends: list[int]
    hard_ends: list[int]
    measure: Callable[[int, int], float]


def _strip_end(line: str, a: int, b: int) -> int:
    """行尾空白不画, 量宽度时要先把这段排除掉"""
    while b > a and line[b - 1].isspace():
        b -= 1
    return b


def _plain_layout(line: str, font: ImageFont.FreeTypeFont) -> _Layout:
    """纯文本: 每个码位一个单元, 宽度用真实前缀测量"""
    n = len(line)
    hard = [i for i in range(1, n) if not _attaches(line[i])]
    hard.append(n)
    soft = [i for i in hard if i == n or _can_break(line[i - 1], line[i])]

    def measure(a: int, b: int) -> float:
        b = _strip_end(line, a, b)
        return font.getlength(line[a:b]) if b > a else 0.0

    return _Layout(soft, hard, measure)


def _emoji_layout(line: str, font: ImageFont.FreeTypeFont) -> _Layout:
    """emoji 模式: 簇内不断, 宽度按簇求和 (与 ``line_width`` 同一规则)"""
    n = len(line)
    starts: list[int] = []
    ends: list[int] = []
    widths: list[float] = []
    width_prefix = [0.0]
    inside_emoji = [False] * (n + 1)
    emoji_boundaries: set[int] = set()
    pos = 0
    for chunk, is_emoji in split_clusters(line):
        end = pos + len(chunk)
        starts.append(pos)
        ends.append(end)
        widths.append(unit_width(chunk, is_emoji, font, emoji_as_square=True))
        width_prefix.append(width_prefix[-1] + widths[-1])
        if is_emoji:
            # 簇内只有首尾能断, 中间这些位置不能
            for k in range(pos + 1, end):
                inside_emoji[k] = True
            emoji_boundaries.add(pos)
            emoji_boundaries.add(end)
        pos = end

    def measure(a: int, b: int) -> float:
        b = _strip_end(line, a, b)
        if b <= a:
            return 0.0
        first = bisect.bisect_right(starts, a) - 1
        last = bisect.bisect_right(starts, b - 1) - 1
        if first == last:
            # 落在同一个簇里: 只可能是 emoji 簇本身, 或者簇内的一段文字
            return (
                widths[first]
                if a == starts[first] and b == ends[first]
                else (font.getlength(line[a:b]))
            )
        total = 0.0
        # 首尾两个簇可能是被切开的半段, 只量实际画出来的那部分
        total += (
            widths[first]
            if a == starts[first]
            else font.getlength(line[a : ends[first]])
        )
        total += width_prefix[last] - width_prefix[first + 1]
        total += (
            widths[last] if b == ends[last] else font.getlength(line[starts[last] : b])
        )
        return total

    hard = [i for i in range(1, n) if not inside_emoji[i] and not _attaches(line[i])]
    hard.append(n)
    soft = [
        i
        for i in hard
        if i == n
        or (
            # 簇边界可以断, 但仍然要守禁则; 簇内位置不在 hard 里, 到不了这里
            _kinsoku_ok(line[i - 1], line[i])
            if i in emoji_boundaries
            else _can_break(line[i - 1], line[i])
        )
    ]
    return _Layout(soft, hard, measure)


def _fill(
    start: int,
    floor: int,
    ceiling: int,
    layout: _Layout,
    limit: float,
) -> int:
    """在 ``floor`` 到 ``ceiling`` 之间的单元边界里找最远的、放得下的位置

    找不到比 ``floor`` 更远的就原样返回 ``floor``: 这一步只负责"还能不能再塞",
    不负责保证前进, 前进由调用方保证。

    先指数探测再二分: 长不可断串里 ``ceiling`` 可能离得很远, 一上来就取中点会量
    几千个字符的前缀, 而真正放得下的范围通常只有一行的宽度。
    """
    hard = layout.hard_ends
    hi = bisect.bisect_right(hard, ceiling) - 1
    fit = -1
    idx = bisect.bisect_right(hard, floor)
    step = 1
    while idx <= hi:
        if layout.measure(start, hard[idx]) > limit:
            break
        fit = idx
        if idx == hi:
            return hard[hi]
        idx = min(idx + step, hi)
        step *= 2
    if fit < 0:
        return floor
    lo, high = fit, idx
    while high - lo > 1:
        mid = (lo + high) // 2
        if layout.measure(start, hard[mid]) <= limit:
            lo = mid
        else:
            high = mid
    return hard[lo]


def _find_cut(start: int, layout: _Layout, limit: float) -> int:
    """本行最远能放到哪里; 结果总大于 ``start``, 保证断行循环一定前进"""
    soft = layout.soft_ends
    line_end = soft[-1]
    first = bisect.bisect_right(soft, start)
    last = len(soft) - 1
    # 指数探测找一个放得下的可断点和一个放不下的, 再二分收尾
    fit = -1
    idx = first
    step = 1
    while idx <= last:
        if layout.measure(start, soft[idx]) > limit:
            break
        fit = idx
        if idx == last:
            return line_end
        idx = min(idx + step, last)
        step *= 2
    if fit < 0:
        # 第一个可断点就放不下: 这个单元自己比整行还宽, 退到单元级硬断
        cut = _fill(start, start, soft[first], layout, limit)
        if cut > start:
            return cut
        # 一个单元都放不下, 也要让它单独占一行, 否则断行循环原地打转
        hard = layout.hard_ends
        j = bisect.bisect_right(hard, start)
        return hard[j] if j < len(hard) else soft[first]
    lo, hi = fit, idx
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if layout.measure(start, soft[mid]) <= limit:
            lo = mid
        else:
            hi = mid
    # 只有"下一个词自己就比整行宽"时才在它内部硬断; 否则整词挪到下一行, 不劈开词
    if layout.measure(soft[lo], soft[hi]) > limit:
        return _fill(start, soft[lo], soft[hi], layout, limit)
    return soft[lo]


def _wrap_line(line: str, limit: float, layout: _Layout) -> list[str]:
    """把一行按宽度切开; 每行行尾的空白都不画, 也就不用算进宽度"""
    n = len(line)
    out: list[str] = []
    start = 0
    while start < n:
        cut = _find_cut(start, layout, limit)
        # 判据量的是剥掉行尾空白的串, 输出也必须剥掉, 否则量出来的和画出来的又不是一回事
        piece = line[start:cut].rstrip()
        if cut < n:
            # 软换行落点是空白时, 两侧的空白都是排版噪音, 不画
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
    比整行还宽时 (长路径、URL) 才硬断。每行行尾的空白都不保留, 软断行的下一行
    也不以空白开头。
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
