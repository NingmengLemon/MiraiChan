from io import BytesIO
import hashlib

from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from PIL import Image, ImageOps, ImageDraw
from yarl import URL

from lemony_utils.images import default_font_cache
from lemony_utils.templates import async_http
from lemony_utils.consts import http_headers
from .models import PredictResultEntity


def preprocess(img: BytesIO):
    pimg = Image.open(img).convert("RGBA")
    w, h = pimg.size
    if w > 512 and h > 512:
        pimg = ImageOps.cover(pimg, (512, 512))
    result = BytesIO()
    pimg.save(result, "png")
    return result


async def get_reply(adapter: Adapter, event: MessageEvent):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        return
    return msg


def calc_hash(b: bytes):
    return hashlib.sha256(b).hexdigest()


def draw_boxs(image: BytesIO, data: list[PredictResultEntity], font_size=20, width=2):
    pimg = Image.open(image).convert("RGBA")
    draw = ImageDraw.Draw(pimg)
    for entity in data:
        draw.rectangle(entity["box"], width=width, outline=(255, 0, 0, 255))
        draw.text(
            (entity["box"][0] + width, entity["box"][1]),
            entity["class_name"] + f" {entity['score']:.4f}",
            font=default_font_cache.use(font_size),
            fill=(255, 0, 0, 255),
        )
    result = BytesIO()
    pimg.save(result, "png")
    return result


async def fetch_image(url: URL | str):
    async with async_http(
        URL(url).with_scheme("http"), "get", headers=http_headers
    ) as resp:
        resp.raise_for_status()
        return BytesIO(await resp.content.read())
