import base64
from contextlib import contextmanager
from io import BytesIO

from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface
from melobot.protocols.onebot.v11.adapter.segment import TextSegment

from PIL import Image, ImageOps, ImageFont, ImageDraw


_ApplyGraSupports = str | BytesIO | Image.Image
_RatioPoint = tuple[float, float]
_RGBAColor = tuple[int, int, int, int]


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
    lines = [s[i : i + line_length] for i in range(0, len(s), line_length)]
    return lines


@contextmanager
def open_font(font: str | BytesIO, size: float = 10):
    fonto = ImageFont.truetype(font, size=size)
    yield fonto


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
        canvas.paste(
            ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0)
        )
    result = Image.alpha_composite(canvas, mask)
    draw = ImageDraw.Draw(result)

    sender = msg["sender"]
    msgsegs = msg["message"]
    msgtexts = []
    for seg in msgsegs:
        if isinstance(seg, TextSegment):
            msgtexts.append(seg.data["text"])
    with open_font(fontfile, size=52) as font:
        draw.text(
            (1340, 785),
            (
                f"—— {sender.title}\n({sender.nickname})"
                if sender.title
                else f"—— {sender.nickname}"
            ),
            fill=(128, 128, 128, 255),
            font=font,
        )
    with open_font(fontfile, size=72) as font:
        draw.text(
            (996, 325),
            "\n".join(wrap_text(" ".join(msgtexts), 15)),
            fill=(255, 255, 255, 255),
            align="center",
            font=font,
        )
    fp = BytesIO()
    result.save(fp, format="PNG")
    return fp


if __name__ == "__main__":
    pass
