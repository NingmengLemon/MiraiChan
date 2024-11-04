import base64
from contextlib import contextmanager
from io import BytesIO

from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface

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
    font = ImageFont.truetype(font, size=size)
    try:
        yield font
    finally:
        font.close()


def make_image(
    avatar: _ApplyGraSupports | None,
    mask: _ApplyGraSupports,
    font: str | BytesIO,
    msg: _GetMsgEchoDataInterface,
):
    bg_color = (255, 255, 255, 255)
    mask = _standardize(mask)
    canvas = Image.new("RGBA", size=(1920, 1080), color=bg_color)
    font = ImageFont.truetype(font, size=72)
    if avatar:
        avatar = _standardize(avatar)
        canvas.paste(
            ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0, 1080, 1080)
        )
    result = Image.alpha_composite(canvas, mask)
    draw = ImageDraw.Draw(result)

    sender = msg["sender"]
    draw.text(
        (1366, 768),
        "\n".join(wrap_text(sender.title or sender.nickname, 10)),
        fill=(255, 255, 255),
        font=font,
    )
    fp = BytesIO()
    result.save(fp, "png")
    result.show()
    return b64encode(fp.read())


def b64encode(data: bytes):
    return "base64://" + base64.b64encode(data).decode("utf-8")


if __name__ == "__main__":
    pass
