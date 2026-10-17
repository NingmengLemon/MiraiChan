"""聊天记录样式 (``.mq``)。

``layout`` 只做几何计算, 在最终像素坐标系里工作 (倍率在开头一次性乘进样式);
``paint`` 只按布局结果绘制。画布尺寸在 ``layout`` 里算出, 超预算时在分配画布前报错。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from PIL import Image, ImageDraw, ImageOps

from ..model import ImageElement, QuoteMessage, TextElement
from .errors import CanvasTooLarge
from .text import FontProvider, TextBlock, draw_text_block, layout_text

__all__ = ["ChatLayout", "ChatStyle", "layout_chat", "paint_chat", "render_chat"]

Color = tuple[int, int, int, int]


def _hex(color: str) -> Color:
    c = color.lstrip("#")
    if len(c) == 6:
        c += "ff"
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16))


@dataclass(frozen=True, slots=True)
class ChatStyle:
    edge: int = 20
    between_msgs: int = 10
    between_senders: int = 60
    avatar_size: int = 90
    padding: int = 12
    radius: int = 10
    wrap_width: int = 512
    max_image_height: int = 1536
    line_spacing: int = 10
    text_size: int = 28
    name_size: int = 26
    id_size: int = 22
    name_id_gap: int = 10
    triangle: int = 10
    background: str = "#ffffff"
    bubble: str = "#4c5b6f"
    bubble_text: str = "#ffffff"
    name: str = "#424f62"
    # QQ 号刻意用很浅的颜色, 相当于水印
    user_id: str = "#dae5e9"

    def scaled(self, k: float) -> "ChatStyle":
        ints = {
            name: max(1, round(getattr(self, name) * k))
            for name in (
                "edge",
                "between_msgs",
                "between_senders",
                "avatar_size",
                "padding",
                "radius",
                "wrap_width",
                "max_image_height",
                "line_spacing",
                "text_size",
                "name_size",
                "id_size",
                "name_id_gap",
                "triangle",
            )
        }
        return replace(self, **ints)


@dataclass(frozen=True, slots=True)
class PlacedText:
    x: int
    y: int
    block: TextBlock


@dataclass(frozen=True, slots=True)
class PlacedImage:
    x: int
    y: int
    width: int
    height: int
    key: str


@dataclass(frozen=True, slots=True)
class PlacedBubble:
    x: int
    y: int
    width: int
    height: int
    with_triangle: bool
    texts: tuple[PlacedText, ...]
    images: tuple[PlacedImage, ...]


@dataclass(frozen=True, slots=True)
class PlacedHeader:
    avatar_xy: tuple[int, int]
    sender_id: int
    name: PlacedText
    user_id: PlacedText


@dataclass(frozen=True, slots=True)
class ChatLayout:
    width: int
    height: int
    style: ChatStyle
    headers: tuple[PlacedHeader, ...]
    bubbles: tuple[PlacedBubble, ...]


def _fit_image(size: tuple[int, int], style: ChatStyle, k: float) -> tuple[int, int]:
    """不超过气泡宽与高度上限; 小图只按倍率放大, 不撑满"""
    w, h = size
    w, h = max(1, round(w * k)), max(1, round(h * k))
    r = min(1.0, style.wrap_width / w, style.max_image_height / h)
    return max(1, round(w * r)), max(1, round(h * r))


def layout_chat(
    messages: Sequence[QuoteMessage],
    *,
    image_sizes: Mapping[str, tuple[int, int]],
    fonts: FontProvider,
    style: ChatStyle = ChatStyle(),  # noqa: B008 - frozen dataclass, 共享默认实例是安全的
    scale: float = 1.0,
    max_pixels: int | None = None,
    placeholder_size: tuple[int, int] = (256, 256),
) -> ChatLayout:
    if not messages:
        raise ValueError("no messages to lay out")
    s = style.scaled(scale)
    text_font = fonts(s.text_size)
    name_font = fonts(s.name_size)
    id_font = fonts(s.id_size)

    x_avatar = s.edge
    x_bubble = s.avatar_size + 2 * s.edge
    y = 0
    right = 0
    last_sender: int | None = None
    headers: list[PlacedHeader] = []
    bubbles: list[PlacedBubble] = []

    for msg in messages:
        new_sender = msg.sender_id != last_sender
        if last_sender is None:
            y += s.edge + s.avatar_size // 2
        elif new_sender:
            y += s.between_senders
        else:
            y += s.between_msgs

        if new_sender:
            name_block = layout_text(msg.display_name, name_font)
            id_block = layout_text(f"({msg.sender_id})", id_font)
            baseline = y - s.between_msgs
            name_y = baseline - name_block.height
            id_x = x_bubble + name_block.width + s.name_id_gap
            # 两段文字底边对齐
            id_y = baseline - id_block.height
            headers.append(
                PlacedHeader(
                    avatar_xy=(x_avatar, y - s.avatar_size // 2),
                    sender_id=msg.sender_id,
                    name=PlacedText(x_bubble, name_y, name_block),
                    user_id=PlacedText(id_x, id_y, id_block),
                )
            )
            right = max(right, id_x + id_block.width)

        inner_x = x_bubble + s.padding
        cy = y + s.padding
        texts: list[PlacedText] = []
        images: list[PlacedImage] = []
        content_w = 0
        elements = msg.elements or (TextElement("[空消息]"),)
        for i, el in enumerate(elements):
            if i:
                cy += s.padding
            if isinstance(el, TextElement):
                block = layout_text(
                    el.text, text_font, max_width=s.wrap_width, spacing=s.line_spacing
                )
                texts.append(PlacedText(inner_x, cy, block))
                content_w = max(content_w, block.width)
                cy += block.height
            elif isinstance(el, ImageElement):
                key = el.ref.key
                w, h = _fit_image(image_sizes.get(key, placeholder_size), s, scale)
                images.append(PlacedImage(inner_x, cy, w, h, key))
                content_w = max(content_w, w)
                cy += h
        bubble_w = content_w + 2 * s.padding
        bubble_h = cy + s.padding - y
        bubbles.append(
            PlacedBubble(
                x=x_bubble,
                y=y,
                width=bubble_w,
                height=bubble_h,
                with_triangle=new_sender,
                texts=tuple(texts),
                images=tuple(images),
            )
        )
        right = max(right, x_bubble + bubble_w)
        y += bubble_h
        last_sender = msg.sender_id

    width = right + s.edge
    height = y + s.edge
    if max_pixels is not None and width * height > max_pixels:
        raise CanvasTooLarge(width, height, max_pixels)
    return ChatLayout(
        width=width,
        height=height,
        style=s,
        headers=tuple(headers),
        bubbles=tuple(bubbles),
    )


def _circle(img: Image.Image, size: int) -> Image.Image:
    img = ImageOps.fit(img.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
    # 用 4 倍蒙版画圆再缩小, 边缘才平滑
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def paint_chat(
    layout: ChatLayout,
    *,
    images: Mapping[str, Image.Image],
    avatars: Mapping[int, Image.Image],
    emojis: Mapping[str, Image.Image],
    fonts: FontProvider,
    placeholder: Image.Image,
) -> Image.Image:
    s = layout.style
    canvas = Image.new("RGBA", (layout.width, layout.height), _hex(s.background))
    draw = ImageDraw.Draw(canvas)
    bubble_color = _hex(s.bubble)

    for h in layout.headers:
        avatar = avatars.get(h.sender_id, placeholder)
        canvas.alpha_composite(_circle(avatar, s.avatar_size), h.avatar_xy)
        draw_text_block(
            canvas,
            (h.name.x, h.name.y),
            h.name.block,
            fonts(s.name_size),
            fill=_hex(s.name),
            emojis=emojis,
        )
        draw_text_block(
            canvas,
            (h.user_id.x, h.user_id.y),
            h.user_id.block,
            fonts(s.id_size),
            fill=_hex(s.user_id),
            emojis=emojis,
        )

    text_font = fonts(s.text_size)
    for b in layout.bubbles:
        draw.rounded_rectangle(
            (b.x, b.y, b.x + b.width, b.y + b.height),
            radius=s.radius,
            fill=bubble_color,
        )
        if b.with_triangle:
            t = s.triangle
            top = b.y + round(1.5 * t)
            draw.polygon(
                [(b.x, top), (b.x, top + t), (b.x - t, top + t // 2)],
                fill=bubble_color,
            )
        for pt in b.texts:
            draw_text_block(
                canvas,
                (pt.x, pt.y),
                pt.block,
                text_font,
                fill=_hex(s.bubble_text),
                emojis=emojis,
            )
        for pi in b.images:
            src = images.get(pi.key, placeholder).convert("RGBA")
            tile = Image.new("RGBA", (pi.width, pi.height), bubble_color)
            tile.alpha_composite(
                src.resize((pi.width, pi.height), Image.Resampling.LANCZOS)
            )
            canvas.alpha_composite(tile, (pi.x, pi.y))
    return canvas


def render_chat(
    messages: Sequence[QuoteMessage],
    *,
    images: Mapping[str, Image.Image],
    avatars: Mapping[int, Image.Image],
    emojis: Mapping[str, Image.Image],
    fonts: FontProvider,
    placeholder: Image.Image,
    style: ChatStyle = ChatStyle(),  # noqa: B008 - frozen dataclass, 共享默认实例是安全的
    scale: float = 1.0,
    max_pixels: int | None = None,
) -> Image.Image:
    layout = layout_chat(
        messages,
        image_sizes={k: v.size for k, v in images.items()},
        fonts=fonts,
        style=style,
        scale=scale,
        max_pixels=max_pixels,
        placeholder_size=placeholder.size,
    )
    return paint_chat(
        layout,
        images=images,
        avatars=avatars,
        emojis=emojis,
        fonts=fonts,
        placeholder=placeholder,
    )
