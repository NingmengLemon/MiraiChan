import base64
import math
from collections.abc import Iterable

from PIL import Image, ImageDraw


def to_full_width(text: str):
    """半角英文字符转全角"""
    return "".join([chr(ord(c) + 0xFEE0) if 33 <= ord(c) <= 126 else c for c in text])


def calc_eudist(p1: Iterable[float], p2: Iterable[float]):
    """欧几里得空间距离"""
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(p1, p2, strict=False)))


def bytes_to_b64_url(b: bytes):
    return "base64://" + base64.b64encode(b).decode("utf-8")


def crop_to_circle(img: Image.Image) -> Image.Image:
    """裁成正方形再套一个圆形遮罩 (头像用)"""
    img = img.convert("RGBA")
    width, height = img.size

    size = min(width, height)
    left = (width - size) // 2
    top = (height - size) // 2
    img_cropped = img.crop((left, top, left + size, top + size))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img_cropped.putalpha(mask)
    return img_cropped.copy()
