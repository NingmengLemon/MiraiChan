"""名言卡片样式 (``.q``): 1920x1080, 左侧头像, 右侧深色底上的正文与署名。

配色按头像做 MD3 动态取色, 见 ``card_colors``。

只画文字; 目标消息没有文字时由上层提示改用聊天样式。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from lemony_images import (
    SchemeVariant,
    contrast_ratio,
    readable_tone,
    scheme_from_color,
    source_color,
)
from PIL import Image, ImageOps

from .text import FontProvider, draw_text_block, fit_text

__all__ = ["CardColors", "CardStyle", "card_colors", "card_signature", "render_card"]

Color = tuple[int, int, int, int]
Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class CardStyle:
    size: tuple[int, int] = (1920, 1080)
    background: Color = (255, 255, 255, 255)
    # 头像无彩色时的静态配色; 有彩色时由 card_colors 按头像生成
    panel: Color = (19, 19, 21, 255)
    text_box: Box = (1000, 325, 1850, 675)
    text_max_size: int = 72
    text_min_size: int = 10
    signature_box: Box = (1140, 945, 1850, 1055)
    signature_max_size: int = 36
    signature_min_size: int = 10
    signature_color: Color = (128, 128, 128, 255)
    min_contrast: float = 4.5


def card_signature(card: str | None, nickname: str | None, fallback: str) -> str:
    card = (card or "").strip()
    nickname = (nickname or "").strip()
    if card and nickname and card != nickname:
        return f"—— {card}\n({nickname})"
    return f"—— {card or nickname or fallback}"


@dataclass(frozen=True, slots=True)
class CardColors:
    panel: Color
    text: Color
    signature: Color


def card_colors(avatar: Image.Image | None, style: CardStyle) -> CardColors:
    """由头像生成卡片配色。

    取头像的 MD3 源色生成深色配色: 遮罩底色用 surface_container, 正文用 primary,
    署名用 outline (比正文暗一档, 对应静态配色里的灰色)。
    头像缺失或无彩色 (灰度 / 全透明) 时用 style 里的静态配色。
    正文或署名与底色的对比度不足 style.min_contrast 时, 在源色色相下调明度补足。
    """
    static = CardColors(style.panel, (255, 255, 255, 255), style.signature_color)
    if avatar is None:
        return static
    source = source_color(avatar)
    if source is None:
        return static
    # FIDELITY 与 CONTENT 都贴近源色, 前者生成快约 9 倍
    scheme = scheme_from_color(source, dark=True, variant=SchemeVariant.FIDELITY)
    panel = scheme["surface_container"]
    text = scheme["primary"]
    if contrast_ratio(text, panel) < style.min_contrast:
        text = readable_tone(
            source, background=panel, min_contrast=style.min_contrast, prefer=80
        )
    signature = scheme["outline"]
    if contrast_ratio(signature, panel) < style.min_contrast:
        signature = readable_tone(
            signature, background=panel, min_contrast=style.min_contrast, prefer=60
        )
    return CardColors(panel, text, signature)


def _tint(mask: Image.Image, color: Color) -> Image.Image:
    """保留遮罩的 alpha 渐变, 把颜色换成 color"""
    out = Image.new("RGBA", mask.size, (*color[:3], 255))
    out.putalpha(mask.getchannel("A"))
    return out


def _center_in(box: Box, w: int, h: int) -> tuple[int, int]:
    x0, y0, x1, y1 = box
    return x0 + (x1 - x0 - w) // 2, y0 + (y1 - y0 - h) // 2


def render_card(
    text: str,
    signature: str,
    *,
    avatar: Image.Image | None,
    mask: Image.Image,
    emojis: Mapping[str, Image.Image],
    fonts: FontProvider,
    style: CardStyle = CardStyle(),  # noqa: B008 - frozen dataclass, 共享默认实例是安全的
) -> Image.Image:
    h = style.size[1]
    canvas = Image.new("RGBA", style.size, style.background)
    if avatar is not None:
        canvas.alpha_composite(
            ImageOps.contain(avatar.convert("RGBA"), (h, h), Image.Resampling.LANCZOS)
        )
    if mask.size != style.size:
        mask = mask.resize(style.size, Image.Resampling.LANCZOS)
    colors = card_colors(avatar, style)
    canvas.alpha_composite(_tint(mask.convert("RGBA"), colors.panel))

    # 署名首行带破折号, 第二行的 (昵称) 右对齐到名片末尾, 读起来像落款
    for content, box, max_size, min_size, color, align in (
        (
            text,
            style.text_box,
            style.text_max_size,
            style.text_min_size,
            colors.text,
            "left",
        ),
        (
            signature,
            style.signature_box,
            style.signature_max_size,
            style.signature_min_size,
            colors.signature,
            "right",
        ),
    ):
        font, block = fit_text(
            content,
            fonts,
            box_width=box[2] - box[0],
            box_height=box[3] - box[1],
            max_size=max_size,
            min_size=min_size,
        )
        draw_text_block(
            canvas,
            _center_in(box, block.width, block.height),
            block,
            font,
            fill=color,
            emojis=emojis,
            align=align,
        )
    return canvas
