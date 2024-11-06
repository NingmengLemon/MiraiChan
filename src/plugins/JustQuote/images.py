from contextlib import contextmanager
from io import BytesIO
from urllib.parse import quote_plus

from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface
from melobot.protocols.onebot.v11.adapter.segment import TextSegment

from PIL import Image, ImageOps, ImageFont, ImageDraw
import pilmoji

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
    with pilmoji.Pilmoji(
        result,
        # emoji_position_offset=(0, fs // 3),
        source=(_emoji_source or pilmoji.source.GoogleEmojiSource),
    ) as draw:
        fs, wrapped = calc_font_size(
            authortext,
            max_font_size=36,
            box_width=480,
            box_height=210,
            fontcache=_font_cache,
        )
        with _font_cache.usec(fs) as font:
            draw.text(
                (1170, 785),
                wrapped,
                fill=(128, 128, 128, 255),
                font=font,
            )
        fs, wrapped = calc_font_size(
            msgtext,
            max_font_size=72,
            box_width=864,
            box_height=288,
            min_font_size=10,
            fontcache=_font_cache,
        )
        with _font_cache.usec(fs) as font:
            draw.text(
                (996, 325),
                wrapped,
                fill=(255, 255, 255, 255),
                align="left",
                font=font,
            )
    fp = BytesIO()
    result.save(fp, format="PNG")
    return fp


if __name__ == "__main__":
    pass
