from io import BytesIO
import math

from melobot.protocols.onebot.v11.adapter.echo import (
    GetMsgEcho,
)

from PIL import Image, ImageOps


_ApplyGraSupports = str | BytesIO | Image.Image


def apply_gradient(
    image: _ApplyGraSupports, start_ratio_x=0.5, start_ratio_y=0.5, angle=0
):
    """为图像应用透明渐变效果

    角度从x坐标轴方向开始顺时针，例如 0 表示从左到右，90 表示从上到下，45 表示从左上到右下

    Powered by ChatGPT, 致敬传奇 GPT 驾驶员凝萌"""
    if isinstance(image, (str, BytesIO)):
        img = Image.open(image).convert("RGBA")
    elif isinstance(image, Image.Image):
        img = image.convert("RGBA")
    else:
        raise ValueError(
            "Invalid image input. Provide a file path or a PIL image object."
        )

    width, height = img.size
    start_x = int(width * start_ratio_x)
    start_y = int(height * start_ratio_y)

    mask = Image.new("L", (width, height), 255)

    angle_rad = math.radians(angle)
    delta_x = math.cos(angle_rad)
    delta_y = math.sin(angle_rad)
    max_distance = math.sqrt(width**2 + height**2)

    for x in range(width):
        for y in range(height):
            distance = (x - start_x) * delta_x + (y - start_y) * delta_y
            alpha = 255 * (1 - max(0, min(1, distance / max_distance)))
            mask.putpixel((x, y), int(alpha))

    img.putalpha(mask)
    return img


def make_image(avatar: _ApplyGraSupports, msg: GetMsgEcho):
    avatar = apply_gradient(avatar, start_ratio_x=0.5)
    canvas = Image.new("RGBA", size=(1920, 1080), color=(0, 0, 0))
    canvas.paste(ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0, 1080, 1080))
    fp = BytesIO()
    canvas.save(fp, "png")
    return fp
