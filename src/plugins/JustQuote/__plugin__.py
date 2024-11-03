from io import BytesIO
from melobot import Plugin, get_logger
from melobot.protocols.onebot.v11.adapter.event import (
    GroupMessageEvent,
)
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, Segment
from melobot.protocols.onebot.v11 import on_command, Adapter
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
from lemony_utils.consts import http_headers
from lemony_utils.asyncutils import run_as_async
from lemony_utils.templates import async_http
from .images import make_image


class QuoteConfig(BaseModel):
    do_upload: bool = False
    update_folder: str = "群U的怪话"
    font: str = "fonts/NotoSansSC-Medium.ttf"


cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=QuoteConfig, filename="quoter_conf.json")
)
cfgloader.load_config()
logger = get_logger()


async def make_quote(msgsegs: list[Segment], avatar: str | None = None):
    avatar_img = await fetch_image(avatar)
    return make_image(avatar_img, msgsegs)


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
    sender = msg.data["sender"]
    msgsegs = msg.data["message"]
    image = await make_quote(
        msgsegs,
        f"https://q.qlogo.cn/headimg_dl?dst_uin={sender.user_id}&spec=640&img_type=jpg",
    )
    await adapter.send_image("[群U的怪话]", raw=image.read())


class Quoter(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (quote,)
