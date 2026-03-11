import base64
import math
from collections.abc import Iterable


def to_full_width(text: str):
    """半角英文字符转全角"""
    return "".join([chr(ord(c) + 0xFEE0) if 33 <= ord(c) <= 126 else c for c in text])


def calc_eudist(p1: Iterable[float], p2: Iterable[float]):
    """欧几里得空间距离"""
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(p1, p2)))


def bytes_to_b64_url(b: bytes):
    return "base64://" + base64.b64encode(b).decode("utf-8")
