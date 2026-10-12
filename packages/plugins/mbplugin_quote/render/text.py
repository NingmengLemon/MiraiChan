"""感知 emoji 的文本测量、断行与绘制。

测量和绘制用同一套规则: 文本按字体实测宽度, emoji 一律占一个字号宽的方块。
emoji 图片由调用方事先取好放进映射里, 这里不做任何网络 IO; 映射里没有的 emoji
退回用字体本身的字形绘制 (宽度仍按方块计, 保证排版不变)。
"""

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import emoji as emoji_lib
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

_WORD_RE = re.compile(r"[A-Za-z0-9_'\-.,:;!?%]")
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
        n = len(self.lines)
        if n == 0:
            return 0
        return n * self.line_height + (n - 1) * self.spacing


def _units(line: str) -> list[Run]:
    """一行文本拆成最小单元: emoji 簇整体一个, 其余逐字符"""
    out: list[Run] = []
    pos = 0
    for m in emoji_lib.emoji_list(line):
        out.extend(Run(c, False) for c in line[pos : m["match_start"]])
        out.append(Run(m["emoji"], True))
        pos = m["match_end"]
    out.extend(Run(c, False) for c in line[pos:])
    return out


def extract_emojis(texts: Iterable[str]) -> set[str]:
    return {m["emoji"] for t in texts for m in emoji_lib.emoji_list(t)}


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return max(ascent + descent, int(font.size))


def _unit_width(u: Run, font: ImageFont.FreeTypeFont) -> float:
    return float(font.size) if u.is_emoji else font.getlength(u.text)


def _merge(units: list[Run]) -> tuple[Run, ...]:
    merged: list[Run] = []
    for u in units:
        if merged and not u.is_emoji and not merged[-1].is_emoji:
            merged[-1] = Run(merged[-1].text + u.text, False)
        else:
            merged.append(u)
    return tuple(merged)


def _runs_width(runs: Iterable[Run], font: ImageFont.FreeTypeFont) -> int:
    return math.ceil(
        sum(float(font.size) if r.is_emoji else font.getlength(r.text) for r in runs)
    )


def _tokens(units: list[Run]) -> list[list[Run]]:
    """把连续的西文字符并成一个词, 尽量不在词中间断行"""
    tokens: list[list[Run]] = []
    for u in units:
        if (
            not u.is_emoji
            and _WORD_RE.match(u.text)
            and tokens
            and tokens[-1]
            and not tokens[-1][-1].is_emoji
            and _WORD_RE.match(tokens[-1][-1].text)
        ):
            tokens[-1].append(u)
        else:
            tokens.append([u])
    return tokens


def _wrap_line(
    units: list[Run], font: ImageFont.FreeTypeFont, max_width: float | None
) -> list[list[Run]]:
    if max_width is None:
        return [units]
    lines: list[list[Run]] = [[]]
    width = 0.0
    for token in _tokens(units):
        tw = sum(_unit_width(u, font) for u in token)
        if width + tw <= max_width:
            lines[-1].extend(token)
            width += tw
            continue
        if tw <= max_width:
            lines.append([])
            width = 0.0
            # 软换行后行首的空格不画
            token = [u for u in token if u.text != " "] if token[0].text == " " else token
            lines[-1].extend(token)
            width = sum(_unit_width(u, font) for u in token)
            continue
        # 单个词比整行还宽, 只能逐单元硬断
        for u in token:
            uw = _unit_width(u, font)
            if width + uw > max_width and lines[-1]:
                lines.append([])
                width = 0.0
            lines[-1].append(u)
            width += uw
    return lines


def layout_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    max_width: float | None = None,
    spacing: int = 4,
) -> TextBlock:
    lines: list[tuple[Run, ...]] = []
    for raw in text.split("\n"):
        for units in _wrap_line(_units(raw), font, max_width):
            lines.append(_merge(units))
    return TextBlock(
        lines=tuple(lines),
        line_widths=tuple(_runs_width(line, font) for line in lines),
        font_size=int(font.size),
        line_height=_line_height(font),
        spacing=spacing,
    )


def _truncate(
    block: TextBlock, font: ImageFont.FreeTypeFont, max_lines: int, max_width: float
) -> TextBlock:
    """只保留前 max_lines 行, 末行加省略号并保证不超宽"""
    if len(block.lines) <= max_lines:
        return block
    kept = list(block.lines[:max_lines])
    units = [u for r in kept[-1] for u in (_units(r.text) if not r.is_emoji else [r])]
    tail = Run(_ELLIPSIS, False)
    while units and _runs_width([*units, tail], font) > max_width:
        units.pop()
    kept[-1] = _merge([*units, tail])
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
                    icon = img.convert("RGBA").resize(
                        (size, size), Image.Resampling.LANCZOS
                    )
                    canvas.alpha_composite(icon, (round(x), top))
                else:
                    draw.text((x, y), run.text, font=font, fill=fill, anchor="la")
                x += size
            else:
                draw.text((x, y), run.text, font=font, fill=fill, anchor="la")
                x += font.getlength(run.text)
        y += block.line_height + block.spacing
