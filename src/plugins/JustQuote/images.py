from contextlib import contextmanager
from io import BytesIO

from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface
from melobot.protocols.onebot.v11.adapter.segment import TextSegment

from PIL import Image, ImageOps, ImageFont, ImageDraw


_ApplyGraSupports = str | BytesIO | Image.Image


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


def wrap_text(s: str, line_length: int):
    result = []
    for line in s.split("\n"):
        result += [line[i : i + line_length] for i in range(0, len(line), line_length)]
    return result


@contextmanager
def open_font(font: str | BytesIO, size: float = 10):
    fonto = ImageFont.truetype(font, size=size)
    yield fonto


def to_full_width(text: str):
    return "".join([chr(ord(c) + 0xFEE0) if 33 <= ord(c) <= 126 else c for c in text])


def calc_font_size(
    text: str,
    max_font_size: int,
    box_width: int,
    box_height: int,
    min_font_size: int = 20,
):
    word_count = len(text)
    extra_linebreak = text.count("\n")
    fsize = max_font_size
    while (
        word_count * fsize / box_width + extra_linebreak > box_height / fsize
        and fsize > min_font_size
    ):
        fsize -= 1

    return int(box_width / fsize), fsize


def make_image(
    avatar: _ApplyGraSupports | None,
    mask: _ApplyGraSupports,
    fontfile: str | BytesIO,
    msg: _GetMsgEchoDataInterface,
):
    bg_color = (255, 255, 255, 255)
    mask = _standardize(mask)
    canvas = Image.new("RGBA", size=(1920, 1080), color=bg_color)
    if avatar:
        avatar = _standardize(avatar)
        canvas.paste(ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0))
    result = Image.alpha_composite(canvas, mask)
    draw = ImageDraw.Draw(result)

    sender = msg["sender"]
    msgsegs = msg["message"]
    msgtexts = [seg.data["text"] for seg in msgsegs if isinstance(seg, TextSegment)]
    msgtext = to_full_width("\n".join(msgtexts))
    authortext = to_full_width(
        (
            f"—— {sender.card}\n({sender.nickname})"
            if sender.card
            else f"—— {sender.nickname}"
        )
    )
    ll, fs = calc_font_size(authortext, max_font_size=52, box_width=480, box_height=210)
    with open_font(fontfile, size=fs) as font:
        draw.text(
            (1170, 785),
            "\n".join(wrap_text(authortext, ll)),
            fill=(128, 128, 128, 255),
            font=font,
        )
    ll, fs = calc_font_size(msgtext, max_font_size=72, box_width=864, box_height=288)
    with open_font(fontfile, size=fs) as font:
        draw.text(
            (996, 325),
            "\n".join(wrap_text(msgtext, ll)),
            fill=(255, 255, 255, 255),
            align="left",
            font=font,
        )
    fp = BytesIO()
    result.save(fp, format="PNG")
    return fp


if __name__ == "__main__":
    pass
