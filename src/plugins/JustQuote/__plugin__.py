import asyncio
import tempfile
from io import BytesIO
import base64
import os
import time
from melobot import Plugin, get_logger
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.echo import _GetMsgEchoDataInterface
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11 import on_command, Adapter
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
from lemony_utils.consts import http_headers
from lemony_utils.templates import async_http
from lagrange_extended_actions import UploadGroupFileAction

from . import images  # pylint: disable=E0611


class QuoteConfig(BaseModel):
    font: str = "data/fonts/NotoSansSC-Medium.ttf"
    mask: str = "data/quote_mask.png"


os.makedirs("data", exist_ok=True)
os.makedirs("data/fonts", exist_ok=True)
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=QuoteConfig, filename="quoter_conf.json")
)
cfgloader.load_config()
logger = get_logger()
images.load_font(cfgloader.config.font)


async def make_quote(
    msg: _GetMsgEchoDataInterface, avatar: str | None = None
) -> BytesIO:
    avatar_img = await fetch_image(avatar)
    return await asyncio.to_thread(
        images.make_image,
        avatar_img,
        cfgloader.config.mask,
        msg,
    )


async def fetch_image(url: str | None):
    if url:
        try:
            async with async_http(url, "get", headers=http_headers) as resp:
                resp.raise_for_status()
                return BytesIO(await resp.content.read())
        except Exception as e:
            logger.error(f"error while get img, error={e}")


@on_command(".", " ", ["q", "quote"])
async def quote(adapter: Adapter, event: GroupMessageEvent):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        await adapter.send_reply("需要指定目标消息")
        return
    msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
    if not msg.data:
        await adapter.send_reply("目标消息数据获取失败")
        return
    sender = msg.data["sender"]
    image = await make_quote(
        msg.data,
        f"https://q.qlogo.cn/headimg_dl?dst_uin={sender.user_id}&spec=640&img_type=jpg",
    )
    imagebytes = image.getvalue()
    imageb64 = "base64://" + base64.b64encode(imagebytes).decode("utf-8")
    await adapter.send(ImageSegment(file=imageb64))


class Quoter(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (quote,)
