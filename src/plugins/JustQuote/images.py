from io import BytesIO
import math
import numpy as np

from melobot.protocols.onebot.v11.adapter.echo import (
    GetMsgEcho,
)

from PIL import Image, ImageOps


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


def _calc_trans_matrix(size: tuple[int, int], start: _RatioPoint, end: _RatioPoint):
    w, h = size
    x0, y0 = start[0] * w, start[1] * h
    x1, y1 = end[0] * w, end[1] * h
    k = 1 / math.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2)
    a = np.arctan2(x1 - x0, y1 - y0)
    return (
        np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1]])
        @ np.array([[k, 0, 0], [0, k, 0], [0, 0, 1]])
        @ np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1]])
    )


def apply_gradient_generic(
    foreground: _ApplyGraSupports,
    background: _ApplyGraSupports,
    start: _RatioPoint,
    end: _RatioPoint,
) -> Image.Image:
    """为图像应用透明渐变效果，从前景渐变到背景

    两个坐标是比例坐标，
    起始及其之前是前景，终止及其之后是背景，中间区域按比例混合两图，渐变角度由两点连线的角度确定

    返回一个新的图像对象"""
    foreground = _standardize(foreground)
    background = _standardize(background)
    if foreground.size != background.size:
        raise ValueError("前景图像与背景图像尺寸必须相等")
    w, h = foreground.size
    trans = _calc_trans_matrix((w, h), start, end)

    canvas = Image.new("RGBA", size=(w, h))

    for y in range(h):
        for x in range(w):
            mix_ratio = (trans @ np.array([x, y, 1]))[0]
            if mix_ratio <= 0:
                canvas.putpixel((x, y), foreground.getpixel((x, y)))
            elif mix_ratio >= 1:
                canvas.putpixel((x, y), background.getpixel((x, y)))
            else:
                canvas.putpixel(
                    (x, y),
                    tuple(
                        map(
                            lambda f, b, r: int(max(min(f * (1 - r) + b * r, 255), 0)),
                            foreground.getpixel((x, y)),
                            background.getpixel((x, y)),
                            (mix_ratio,) * 4,
                        )
                    ),
                )

    return canvas


def apply_gradient(
    image: _ApplyGraSupports,
    bg_color: _RGBAColor = (0, 0, 0, 0),
    start: _RatioPoint = (0, 0.5),
    end: _RatioPoint = (0, 1.0),
):
    image = _standardize(image)
    bg = Image.new("RGBA", size=image.size, color=bg_color)
    return apply_gradient_generic(image, bg, start, end)


def make_image(avatar: _ApplyGraSupports, msg: GetMsgEcho):
    bg_color = (0, 0, 0, 255)
    avatar = apply_gradient(avatar, bg_color=bg_color)
    canvas = Image.new("RGBA", size=(1920, 1080), color=bg_color)
    canvas.paste(ImageOps.contain(avatar, size=(1080, 1080)), box=(0, 0, 1080, 1080))
    fp = BytesIO()
    canvas.save(fp, "png")
    return fp


if __name__ == "__main__":
    # img = apply_gradient_generic(
    #     "D:/Download/b_54daccd2dd0db9b38801a2c77fe149d2.jpg",
    #     "D:/Download/b_97ca9ae11dc4deaf7f38961e22cdb760.jpg",
    #     start=(0, 0),
    #     end=(1, 1),
    # )
    # img.show()
    img = apply_gradient(
        Image.new("RGBA", (1024, 1024), (255, 255, 255, 255)),
        start=(0, 1),
        end=(1, 0),
        bg_color=(0, 0, 0, 255),
    )
    img.show()
