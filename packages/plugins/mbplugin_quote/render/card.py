"""名言卡片样式 (``.q``): 1920x1080, 左侧头像, 右侧深色底上的正文与署名。

只画文字; 目标消息没有文字时由上层提示改用聊天样式。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from lemony_images import readable_tone, source_color
from PIL import Image, ImageOps

from .text import FontProvider, draw_text_block, fit_text

__all__ = ["CardStyle", "card_signature", "render_card", "text_color_for"]

Color = tuple[int, int, int, int]
Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class CardStyle:
    size: tuple[int, int] = (1920, 1080)
    background: Color = (255, 255, 255, 255)
    # 遮罩右侧的底色, 用来算正文对比度
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


def text_color_for(
    avatar: Image.Image | None, panel: Color, min_contrast: float
) -> Color:
    """按 MD3 动态取色取头像源色, 保持色相与色度, 在 HCT 明度上找与底色对比度达标的颜色。

    头像缺失或无彩色 (灰度 / 全透明) 时用白色。结果确定且保证可读。
    """
    white: Color = (255, 255, 255, 255)
    if avatar is None:
        return white
    source = source_color(avatar)
    if source is None:
        return white
    return readable_tone(source, background=panel, min_contrast=min_contrast, prefer=80)


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
    canvas.alpha_composite(mask.convert("RGBA"))

    for content, box, max_size, min_size, color in (
        (
            text,
            style.text_box,
            style.text_max_size,
            style.text_min_size,
            text_color_for(avatar, style.panel, style.min_contrast),
        ),
        (
            signature,
            style.signature_box,
            style.signature_max_size,
            style.signature_min_size,
            style.signature_color,
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
        )
    return canvas
