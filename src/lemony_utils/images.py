from io import BytesIO
from urllib.parse import quote_plus
from contextlib import contextmanager

from PIL import ImageFont
import pilmoji


class SelfHostSource(pilmoji.source.HTTPBasedSource):
    STYLE = "google"

    def __init__(self, cdn: str):
        super().__init__()
        self._cdn = cdn.rstrip("/") + "/"

    def get_discord_emoji(self, id: int, /):  # pylint: disable=W0622
        return None

    def get_emoji(self, emoji: str, /):
        try:
            return BytesIO(
                self.request(self._cdn + quote_plus(emoji) + "?style=google")
            )
        except Exception:
            return None


class FontCache:
    def __init__(
        self, font_file: str | BytesIO, preload_size_range: range | None = None
    ):
        self._font_file = font_file
        self._font_map: dict[int, ImageFont.FreeTypeFont] = {}
        if preload_size_range:
            for size in preload_size_range:
                self._font_map[size] = ImageFont.truetype(font_file, size=size)

    def use(self, size: int):
        if size in self._font_map:
            return self._font_map[size]
        else:
            self._font_map[size] = ImageFont.truetype(self._font_file, size=size)
            return self._font_map[size]

    @contextmanager
    def usec(self, size: int):
        yield self.use(size=size)


def wrap_text_by_length(s: str, line_length: int):
    result: list[str] = []
    for line in s.splitlines():
        for i in range(0, len(line), line_length):
            result.append(line[i : i + line_length])
    return result


def wrap_text_by_width(
    s: str,
    line_width: int,
    font: ImageFont.FreeTypeFont,
):
    result: list[str] = []
    for line in s.splitlines():
        if not line:
            result.append("")
            continue
        char_widths = [font.getlength(c) for c in line]
        start = 0
        while start < len(line):
            current_width = 0
            end = start
            while end < len(line) and current_width + char_widths[end] <= line_width:
                current_width += char_widths[end]
                end += 1
            result.append(line[start:end])
            start = end
    return result


def to_full_width(text: str):
    return "".join([chr(ord(c) + 0xFEE0) if 33 <= ord(c) <= 126 else c for c in text])


def calc_font_size(
    text: str,
    max_font_size: int,
    box_width: int,
    box_height: int,
    fontcache: FontCache,
    min_font_size: int = 20,
):
    fsize = max_font_size
    while fsize > min_font_size:
        with fontcache.usec(size=fsize) as font:
            wrapped_lines = wrap_text_by_width(text, box_width, font)
            bbox = font.getbbox("意义是无意识")  # 这里要的是字体高度所以填什么都好x
            # getbbox 不认换行符所以像这样
            if (bbox[3] - bbox[1]) * len(wrapped_lines) <= box_height:
                break
        fsize -= 1
    return fsize, "\n".join(wrap_text_by_width(text, box_width, fontcache.use(fsize)))
