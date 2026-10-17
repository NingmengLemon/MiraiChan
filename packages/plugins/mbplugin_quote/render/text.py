"""感知 emoji 的文本测量、断行与绘制。

测量和绘制用同一套规则: 具体数值来自 ``lemony_images.text.metrics`` (行高、emoji
方块宽度、簇切分在这里定义一次, 引用图与 ``lemony_images`` 的绘制层共用), 断行直接
交给 ``lemony_images.text.wrap_text_by_width`` (按词与 CJK 禁则断, 行尾空白不保留),
本模块只负责"块"这一层: 调用断行、块内对齐、超行截断。

emoji 图片由调用方事先取好放进映射里, 这里不做任何网络 IO; 映射里没有的 emoji
退回用字体本身的字形绘制 (宽度仍按方块计, 保证排版不变)。
"""

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from lemony_images.text import (
    block_height,
    fit_to_square,
    line_height,
    split_clusters,
    unit_width,
    wrap_text_by_width,
)
from PIL import Image, ImageDraw, ImageFont

__all__ = [
    "FontProvider",
    "Run",
    "TextBlock",
    "draw_text_block",
    "extract_emojis",
    "fit_text",
    "layout_text",
]

FontProvider = Callable[[int], ImageFont.FreeTypeFont]
Color = tuple[int, int, int, int]

_ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class Run:
    text: str
    is_emoji: bool


@dataclass(frozen=True, slots=True)
class TextBlock:
    lines: tuple[tuple[Run, ...], ...]
    line_widths: tuple[int, ...]
    font_size: int
    line_height: int
    spacing: int

    @property
    def width(self) -> int:
        return max(self.line_widths, default=0)

    @property
    def height(self) -> int:
        return block_height(len(self.lines), self.line_height, self.spacing)


def _line_runs(line: str) -> tuple[Run, ...]:
    """一行文本拆成绘制用的 run: emoji 簇一个, 其余连续文字一个"""
    return tuple(Run(chunk, is_emoji) for chunk, is_emoji in split_clusters(line))


def extract_emojis(texts: Iterable[str]) -> set[str]:
    return {chunk for t in texts for chunk, is_emoji in split_clusters(t) if is_emoji}


def _unit_width(u: Run, font: ImageFont.FreeTypeFont) -> float:
    # 引用图总是按平方块排版: emoji 由图片贴上, 图片缺失时也留出同样宽度
    return unit_width(u.text, u.is_emoji, font, emoji_as_square=True)


def _runs_width(runs: Iterable[Run], font: ImageFont.FreeTypeFont) -> int:
    return math.ceil(sum(_unit_width(r, font) for r in runs))


def layout_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    max_width: float | None = None,
    spacing: int = 4,
) -> TextBlock:
    """把文本排成块; ``max_width`` 为 None 时只按换行符切"""
    lines = (
        text.split("\n")
        if max_width is None
        else wrap_text_by_width(text, max_width, font, emoji_as_square=True)
    )
    blocks = tuple(_line_runs(line) for line in lines)
    return TextBlock(
        lines=blocks,
        line_widths=tuple(_runs_width(line, font) for line in blocks),
        font_size=int(font.size),
        line_height=line_height(font),
        spacing=spacing,
    )


def _merge_runs(units: Iterable[Run]) -> tuple[Run, ...]:
    """相邻的普通文字并成一个 run, 绘制时少走几次分支"""
    merged: list[Run] = []
    for u in units:
        if merged and not u.is_emoji and not merged[-1].is_emoji:
            merged[-1] = Run(merged[-1].text + u.text, False)
        else:
            merged.append(u)
    return tuple(merged)


def _truncate(
    block: TextBlock, font: ImageFont.FreeTypeFont, max_lines: int, max_width: float
) -> TextBlock:
    """只保留前 max_lines 行, 末行加省略号并保证不超宽"""
    if len(block.lines) <= max_lines:
        return block
    kept = list(block.lines[:max_lines])
    # 末行按字符展开再从后往前丢, emoji 簇整体丢; 丢到加上省略号不超宽为止
    units: list[Run] = []
    for run in kept[-1]:
        if run.is_emoji:
            units.append(run)
        else:
            units.extend(Run(ch, False) for ch in run.text)
    tail = Run(_ELLIPSIS, False)
    while units and _runs_width([*units, tail], font) > max_width:
        units.pop()
    kept[-1] = _merge_runs([*units, tail])
    return TextBlock(
        lines=tuple(kept),
        line_widths=tuple(_runs_width(line, font) for line in kept),
        font_size=block.font_size,
        line_height=block.line_height,
        spacing=block.spacing,
    )


def fit_text(
    text: str,
    fonts: FontProvider,
    *,
    box_width: int,
    box_height: int,
    max_size: int,
    min_size: int,
    spacing_ratio: float = 0.15,
) -> tuple[ImageFont.FreeTypeFont, TextBlock]:
    """找能放进盒子的最大字号; 最小字号仍放不下时截断并加省略号"""
    for size in range(max_size, min_size - 1, -1):
        font = fonts(size)
        block = layout_text(
            text, font, max_width=box_width, spacing=round(size * spacing_ratio)
        )
        if block.height <= box_height:
            return font, block
    font = fonts(min_size)
    block = layout_text(
        text, font, max_width=box_width, spacing=round(min_size * spacing_ratio)
    )
    per_line = block.line_height + block.spacing
    max_lines = max(1, (box_height + block.spacing) // per_line)
    return font, _truncate(block, font, max_lines, box_width)


def draw_text_block(
    canvas: Image.Image,
    xy: tuple[int, int],
    block: TextBlock,
    font: ImageFont.FreeTypeFont,
    *,
    fill: Color,
    emojis: Mapping[str, Image.Image],
    align: str = "left",
) -> None:
    """在 xy (块的左上角) 处绘制; align 作用于块内各行"""
    draw = ImageDraw.Draw(canvas)
    x0, y = xy
    size = block.font_size
    for runs, line_width in zip(block.lines, block.line_widths, strict=True):
        if align == "center":
            x = x0 + (block.width - line_width) / 2
        elif align == "right":
            x = x0 + block.width - line_width
        else:
            x = float(x0)
        for run in runs:
            if run.is_emoji:
                img = emojis.get(run.text)
                top = y + (block.line_height - size) // 2
                if img is not None:
                    icon = fit_to_square(img, size)
                    canvas.alpha_composite(
                        icon,
                        (
                            round(x + (size - icon.width) / 2),
                            top + (size - icon.height) // 2,
                        ),
                    )
                else:
                    draw.text((x, y), run.text, font=font, fill=fill, anchor="la")
                x += size
            else:
                draw.text((x, y), run.text, font=font, fill=fill, anchor="la")
                x += font.getlength(run.text)
        y += block.line_height + block.spacing
