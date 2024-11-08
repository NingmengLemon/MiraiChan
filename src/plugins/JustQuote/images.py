import functools
from io import BytesIO

from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface
from melobot.protocols.onebot.v11.adapter.segment import TextSegment

from PIL import Image, ImageOps, ImageDraw

from lemony_utils.images import (
    FontCache,
    SelfHostSource,
    draw_multiline_text_auto,
    get_main_color,
)

_ApplyGraSupports = str | BytesIO | Image.Image
_font_cache: "FontCache" = None
_emoji_source: "SelfHostSource" = None


def load_font(font_file: str | BytesIO):
    global _font_cache
    if _font_cache:
        raise RuntimeError("font file already loaded")
    _font_cache = FontCache(font_file=font_file)


def set_emoji_cdn(cdn: str):
    global _emoji_source
    if _emoji_source:
        raise RuntimeError("emoji source already set")
    _emoji_source = SelfHostSource(cdn=cdn)


def _standardize(image: _ApplyGraSupports):
    if isinstance(image, (str, BytesIO)):
        img = Image.open(image).convert("RGBA")
    elif isinstance(image, Image.Image):
        img = image.convert("RGBA")
    else:
        raise ValueError(
            "Invalid image input. Provide a file path or a PIL image object."
        )
    return img


def make_image(
    avatar: _ApplyGraSupports | None,
    mask: _ApplyGraSupports,
    msg: _GetMsgEchoDataInterface,
):
    bg_color = (255, 255, 255, 255)
    mask = _standardize(mask)
    canvas = Image.new("RGBA", size=(1920, 1080), color=bg_color)
    if avatar:
        avatar = _standardize(avatar)
        canvas.paste(ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0))
    result = Image.alpha_composite(canvas, mask)
    # draw = ImageDraw.Draw(result)

    sender = msg["sender"]
    msgsegs = msg["message"]
    msgtexts = [seg.data["text"] for seg in msgsegs if isinstance(seg, TextSegment)]
    msgtext = "\n".join(msgtexts)
    authortext = (
        f"—— {sender.card}\n({sender.nickname})"
        if sender.card
        else f"—— {sender.nickname}"
    )
    draw = ImageDraw.Draw(result)
    draw_text = functools.partial(
        draw_multiline_text_auto,
        emoji_source=_emoji_source,
        font=_font_cache,
        draw=draw,
    )
    draw_text(
        bbox=(1000, 325, 1850, 675),
        text=msgtext,
        max_font_size=72,
        # fill=(255, 255, 255, 255),
        fill=(get_main_color(avatar) if avatar else (255, 255, 255, 255)),
    )
    draw_text(
        bbox=(1140, 945, 1850, 1055),
        text=authortext,
        max_font_size=36,
        fill=(128, 128, 128, 255),
    )
    fp = BytesIO()
    result.save(fp, format="PNG")
    return fp
