import asyncio
from io import BytesIO
import json

from pydantic import BaseModel

from melobot.utils import lock
from melobot.plugin import Plugin
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.handle import on_command, on_message
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
import aiohttp
from PIL import Image, ImageOps

from configloader import ConfigLoader, ConfigLoaderMetadata
from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http


class NNConfig(BaseModel):
    api: str = "http://127.0.0.1:9656/predict"
    api_key: str | None = None


cfgloader = ConfigLoader(
    ConfigLoaderMetadata(
        model=NNConfig,
        filename="antinailong_conf.json",
    )
)
cfgloader.load_config()
API = cfgloader.config.api
API_KEY = cfgloader.config.api_key


def preproc(img: BytesIO):
    pimg = Image.open(img).convert("RGBA")
    w, h = pimg.size
    if w > 512 or h > 512:
        pimg = ImageOps.contain(pimg, (512, 512))
    result = BytesIO()
    pimg.save(result, "png")
    return result


@lock()
async def predict(img: BytesIO):
    img = await asyncio.to_thread(preproc, img)
    form = aiohttp.FormData()
    form.add_field("image", img.getvalue(), content_type="image/png")
    async with async_http(
        API + (f"?key={API_KEY}" if API_KEY else ""), "post", data=form
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_image(url: str):
    url = url.replace(
        "https://multimedia.nt.qq.com.cn/", "http://multimedia.nt.qq.com.cn/"
    )
    async with async_http(url, "get", headers=http_headers) as resp:
        resp.raise_for_status()
        return BytesIO(await resp.content.read())


@on_command(
    ".",
    " ",
    "recognize",
    # checker=lambda e: e.user_id == checker_factory.owner,
)
async def test_recognize(adapter: Adapter, event: GroupMessageEvent):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        await adapter.send_reply("需要指定目标消息")
        return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        await adapter.send_reply("目标消息数据获取失败")
        return
    imgs = [s for s in msg.data["message"] if isinstance(s, ImageSegment)]
    if not imgs:
        await adapter.send_reply("消息中没有图片")
        return
    try:
        img = await fetch_image(imgs[0].data["file"])
        result = await predict(img)
    except Exception as e:
        await adapter.send_reply(f"出错了: {e}")
    else:
        await adapter.send_reply(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )


@on_message()
async def daemon(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
    imgs = [s for s in event.message if isinstance(s, ImageSegment)]
    if not imgs:
        return
    logger.debug(
        f"checking {event.message_id} by {event.sender.user_id}({event.sender.nickname})"
    )
    for i, img in enumerate(imgs):
        try:
            imgdata = await fetch_image(img.data["file"])
            result = await predict(imgdata)
        except Exception as e:
            logger.error(f"error when recognize: {e}")
            continue
        for entity in result["data"]:
            logger.debug(
                f"found {entity['class_name']} (score={entity['score']}) in img {i}"
            )
            if entity["class_name"] == "nailong" and entity["score"] > 0.7:
                logger.info("nailong detected! try deleting")
                await adapter.delete_msg(event.message_id)
                return
    logger.debug("no nailong found")


class AntiNailong(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (test_recognize,)  # , daemon)
