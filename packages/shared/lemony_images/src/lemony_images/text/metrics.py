"""文本度量: 一行多高、一个单元多宽, 全库只在这里定义。

绘制和拟合必须用同一套规则。以前引用图和 ``layout`` 各算一遍, 两边的行高定义
就开始分叉了, 结果是一边算出放得下、另一边画出来溢出。
"""

import emoji as emoji_lib
from PIL import ImageFont

__all__ = [
    "block_height",
    "emoji_square_width",
    "line_height",
    "line_width",
    "split_clusters",
    "unit_width",
]


def split_clusters(text: str) -> list[tuple[str, bool]]:
    """把文本切成 (片段, 是否 emoji 簇); emoji 簇整体算一块

    ZWJ 序列、肤色修饰、旗帜这些多码位的东西要在排版里当一个单元处理, 按码位
    切会把它们拆到两行去。
    """
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in emoji_lib.emoji_list(text):
        if m["match_start"] > pos:
            out.append((text[pos : m["match_start"]], False))
        out.append((m["emoji"], True))
        pos = m["match_end"]
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def emoji_square_width(font: ImageFont.FreeTypeFont) -> float:
    """emoji 簇在排版里占的宽度: 一个字号宽的方块"""
    return float(font.size)


def unit_width(
    chunk: str,
    is_emoji: bool,
    font: ImageFont.FreeTypeFont,
    *,
    emoji_as_square: bool = True,
) -> float:
    """一个排版单元的宽度

    emoji_as_square=True 时 emoji 簇按一个字号方块计 (绘制层会贴一张同样大小的
    图片上去); False 时按字体实测, 用于直接交给字体绘制的场景。
    """
    if is_emoji and emoji_as_square:
        return emoji_square_width(font)
    return font.getlength(chunk)


def line_width(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    emoji_as_square: bool = True,
) -> float:
    """一行文本的宽度"""
    if not emoji_as_square:
        return font.getlength(text)
    return sum(
        unit_width(chunk, is_emoji, font, emoji_as_square=True)
        for chunk, is_emoji in split_clusters(text)
    )


def line_height(font: ImageFont.FreeTypeFont) -> int:
    """一行的行高。

    取 ``max(ascent + descent, 字号)``。上行与下行给出文字本身的字框, 而 emoji 是
    按字号大小的方块贴上去的: 字体框比字号小时 (有些字体就是这样) 方块会捅出行高,
    所以把字号也算进来。引用图那边一直用的是这个定义。
    """
    return max(sum(font.getmetrics()), int(font.size))


def block_height(lines: int, line_height: int, spacing: int) -> int:
    """多行文本块的总高; 行与行之间才加 spacing, 行尾不加"""
    if lines <= 0:
        return 0
    return lines * line_height + (lines - 1) * spacing
