import base64
import os
from melobot import Plugin, get_logger
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11 import on_command, Adapter
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
from lagrange_extended_actions import UploadGroupFileAction

from .maker import QuoteMaker


class QuoteConfig(BaseModel):
    emoji_cdn: str | None = None
    font: str = "data/fonts/NotoSansSC-Medium.ttf"
    mask: str = "data/quote_mask.png"


os.makedirs("data/fonts", exist_ok=True)
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=QuoteConfig, filename="quoter_conf.json")
)
cfgloader.load_config()
logger = get_logger()
maker = QuoteMaker(
    font=cfgloader.config.font,
    bg_mask=cfgloader.config.mask,
    emoji_cdn=cfgloader.config.emoji_cdn,
)


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
    # logger.debug(msg.data)
    if sender.user_id == event.self_id:
        await adapter.send_reply("不可以引用咱自己的话！")
        return
    image = await maker.make(msg.data, use_imgs=True)
    if image is None:
        await adapter.send_reply("目标消息中没有支持引用的元素")
        return
    imagebytes = image.getvalue()
    imageb64 = "base64://" + base64.b64encode(imagebytes).decode("utf-8")
    await adapter.send(ImageSegment(file=imageb64))


class Quoter(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (quote,)
