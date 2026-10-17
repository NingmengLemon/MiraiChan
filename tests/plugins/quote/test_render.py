"""渲染层测试: 断言几何关系与基本像素性质, 不做像素级金标。

字体用 Pillow 内置的 FreeType 字体, 不依赖 data/fonts。
"""

import pytest
from lemony_images import contrast_ratio
from mbplugin_quote.model import ImageElement, ImageRef, QuoteMessage, TextElement
from mbplugin_quote.render import CanvasTooLarge
from mbplugin_quote.render.card import (
    CardColors,
    CardStyle,
    card_colors,
    card_signature,
    render_card,
)
from mbplugin_quote.render.chat import ChatStyle, layout_chat, render_chat
from mbplugin_quote.render.mask import build_mask
from PIL import Image, ImageChops, ImageFont


def fonts(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.load_default(size)
    assert isinstance(f, ImageFont.FreeTypeFont)
    return f


def msg(sender: int, *elements, name: str | None = None) -> QuoteMessage:
    return QuoteMessage(
        message_id=f"{sender}-{len(elements)}",
        sender_id=sender,
        display_name=name or f"user{sender}",
        nickname=None,
        card=None,
        elements=tuple(elements),
    )


def text(t: str) -> TextElement:
    return TextElement(t)


def image(key: str) -> ImageElement:
    return ImageElement(ImageRef(url=key))


PLACEHOLDER = Image.new("RGBA", (256, 256), (200, 200, 200, 255))


def test_same_sender_shares_one_header() -> None:
    layout = layout_chat(
        [msg(1, text("a")), msg(1, text("b")), msg(2, text("c")), msg(1, text("d"))],
        image_sizes={},
        fonts=fonts,
    )
    assert [h.sender_id for h in layout.headers] == [1, 2, 1]
    assert [b.with_triangle for b in layout.bubbles] == [True, False, True, True]
    s = layout.style
    b = layout.bubbles
    assert b[1].y - (b[0].y + b[0].height) == s.between_msgs
    assert b[2].y - (b[1].y + b[1].height) == s.between_senders


def test_everything_fits_inside_canvas() -> None:
    layout = layout_chat(
        [
            msg(1, text("短"), name="很长很长的群名片" * 4),
            msg(2, text("长消息" * 100), image("wide"), image("tall")),
        ],
        image_sizes={"wide": (4000, 300), "tall": (300, 9000)},
        fonts=fonts,
    )
    s = layout.style
    for b in layout.bubbles:
        assert b.x + b.width <= layout.width - s.edge
        assert b.y + b.height <= layout.height - s.edge
        for t in b.texts:
            assert t.block.width <= s.wrap_width
        for i in b.images:
            assert i.width <= s.wrap_width
            assert i.height <= s.max_image_height
    for h in layout.headers:
        assert h.user_id.x + h.user_id.block.width <= layout.width
        assert h.avatar_xy[1] >= 0


def test_small_images_are_not_stretched() -> None:
    layout = layout_chat(
        [msg(1, image("small"))], image_sizes={"small": (100, 50)}, fonts=fonts
    )
    (pi,) = layout.bubbles[0].images
    assert (pi.width, pi.height) == (100, 50)


def test_scale_multiplies_geometry() -> None:
    messages = [msg(1, text("hello")), msg(2, image("i"))]
    a = layout_chat(messages, image_sizes={"i": (100, 50)}, fonts=fonts)
    b = layout_chat(messages, image_sizes={"i": (100, 50)}, fonts=fonts, scale=2)
    assert b.width == pytest.approx(a.width * 2, rel=0.1)
    assert b.height == pytest.approx(a.height * 2, rel=0.1)
    assert b.bubbles[1].images[0].width == 200


def test_pixel_budget_is_checked_before_allocation() -> None:
    with pytest.raises(CanvasTooLarge):
        layout_chat(
            [msg(i, text("x" * 500)) for i in range(30)],
            image_sizes={},
            fonts=fonts,
            max_pixels=1000 * 1000,
        )


def test_empty_message_gets_placeholder_text() -> None:
    layout = layout_chat([msg(1)], image_sizes={}, fonts=fonts)
    assert len(layout.bubbles[0].texts) == 1


def test_render_chat_smoke() -> None:
    red = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    out = render_chat(
        [msg(1, text("你好 😀")), msg(2, image("img"))],
        images={"img": Image.new("RGBA", (120, 80), (0, 0, 255, 255))},
        avatars={1: red},
        emojis={"😀": red},
        fonts=fonts,
        placeholder=PLACEHOLDER,
    )
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0)) == (255, 255, 255, 255)
    colors = {c for _, c in out.getcolors(maxcolors=1 << 20) or []}
    assert (0, 0, 255, 255) in colors  # 消息图片
    assert ChatStyle().bubble  # 默认样式可用


def test_card_signature() -> None:
    assert card_signature("名片", "昵称", "1") == "—— 名片\n(昵称)"
    assert card_signature("同名", "同名", "1") == "—— 同名"
    assert card_signature(None, "昵称", "1") == "—— 昵称"
    assert card_signature(None, None, "123") == "—— 123"


@pytest.mark.parametrize(
    "avatar_color",
    [(0, 0, 0), (19, 19, 21), (40, 0, 60), (255, 255, 0), (120, 120, 120)],
)
def test_card_text_color_is_readable(avatar_color: tuple[int, int, int]) -> None:
    style = CardStyle()
    avatar = Image.new("RGB", (64, 64), avatar_color)
    colors = card_colors(avatar, style)
    assert contrast_ratio(colors.text, colors.panel) >= style.min_contrast
    assert colors == card_colors(avatar, style)


def test_card_colors_follow_avatar_hue() -> None:
    style = CardStyle()
    # 灰底上一小块红色: 源色取红色, 而不是画面中心的灰
    avatar = Image.new("RGB", (64, 64), (128, 128, 128))
    avatar.paste((200, 50, 50), (0, 0, 16, 16))
    colors = card_colors(avatar, style)
    for r, g, b, _ in (colors.text, colors.panel):
        assert r > g and r > b
    # 署名可读, 但比正文暗
    assert contrast_ratio(colors.signature, colors.panel) >= style.min_contrast
    assert contrast_ratio(colors.signature, colors.panel) < contrast_ratio(
        colors.text, colors.panel
    )
    # 底色仍是深色, 与静态配色一致的定位
    assert contrast_ratio(colors.panel, (0, 0, 0, 255)) < 2


@pytest.mark.parametrize(
    "avatar",
    [None, Image.new("RGB", (64, 64), (128, 128, 128))],
)
def test_card_colors_static_without_hue(avatar: Image.Image | None) -> None:
    style = CardStyle()
    colors = card_colors(avatar, style)
    assert colors == CardColors(
        style.panel, (255, 255, 255, 255), style.signature_color
    )


def test_card_signature_lines_are_right_aligned() -> None:
    style = CardStyle()
    out = render_card(
        "正文",
        card_signature("很长很长的群名片", "短", "1"),
        avatar=None,
        mask=build_mask(style.size),
        emojis={},
        fonts=fonts,
    )
    region = out.crop(style.signature_box).convert("L")
    bg = region.getpixel((0, 0))
    assert isinstance(bg, int)
    ink = region.point(lambda v: 255 if abs(v - bg) > 40 else 0)
    rows = [
        y for y in range(ink.height) if ink.crop((0, y, ink.width, y + 1)).getbbox()
    ]
    # 两行之间有空白行, 按它把墨迹切成上下两行, 比较各自的右端
    gap = next(rows[i] for i in range(1, len(rows)) if rows[i] - rows[i - 1] > 1)
    top = ink.crop((0, rows[0], ink.width, gap)).getbbox()
    bottom = ink.crop((0, gap, ink.width, rows[-1] + 1)).getbbox()
    assert top and bottom
    assert abs(top[2] - bottom[2]) <= 6  # 右端对齐 (允许字形边距差)
    assert bottom[0] > top[0] + 50  # 短的第二行靠右


def test_render_card_smoke() -> None:
    out = render_card(
        "测试文本 " * 30,
        card_signature("名片", "昵称", "1"),
        avatar=Image.new("RGB", (640, 640), (200, 50, 50)),
        mask=build_mask(CardStyle().size),
        emojis={},
        fonts=fonts,
    )
    assert out.size == (1920, 1080)
    # 遮罩被换成按头像生成的底色
    panel = card_colors(Image.new("RGB", (64, 64), (200, 50, 50)), CardStyle()).panel
    assert out.getpixel((1900, 20)) == panel
    # 正文区域里有非底色像素
    region = out.crop(CardStyle().text_box)
    assert len(region.getcolors(maxcolors=1 << 16) or []) > 1


def test_card_takes_the_alpha_channel_of_rgba_masks() -> None:
    style = CardStyle()
    alpha = build_mask(style.size)
    rgba = Image.new("RGBA", style.size, style.panel)
    rgba.putalpha(alpha)  # 旧资源是带底色的 RGBA, 颜色应当被丢掉
    signature = card_signature(None, None, "1")

    def render(mask: Image.Image) -> Image.Image:
        return render_card(
            "正文", signature, avatar=None, mask=mask, emojis={}, fonts=fonts
        )

    # 两张图 alpha 都是 255, 比较 RGB: getbbox 默认只看 alpha 通道
    assert (
        ImageChops.difference(render(rgba), render(alpha)).convert("RGB").getbbox()
        is None
    )
