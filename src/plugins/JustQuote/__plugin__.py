import base64
import os
import time
import aiofiles
from melobot import PluginPlanner
from melobot.log import GenericLogger
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11 import on_command, Adapter
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
import little_helper

from .maker import QuoteMaker

Quoter = PluginPlanner("0.1.0")
little_helper.register(
    "JustQuote",
    {
        "cmd": ".{q|quote}",
        "text": "将回复的消息图片化",
    },
)


class QuoteConfig(BaseModel):
    emoji_cdn: str | None = None
    font: str = "data/fonts/NotoSansSC-Medium.ttf"
    mask: str = "data/quote_mask.png"
    saveto: str | None = "data/record/quotes"
    allow_image: bool = False


os.makedirs("data/fonts", exist_ok=True)
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=QuoteConfig, filename="quoter_conf.json")
)
cfgloader.load_config()
os.makedirs(cfgloader.config.saveto, exist_ok=True)
maker = QuoteMaker(
    font=cfgloader.config.font,
    bg_mask=cfgloader.config.mask,
    emoji_cdn=cfgloader.config.emoji_cdn,
)


@Quoter.use
@on_command(".", " ", ["q", "quote"])
async def quote(adapter: Adapter, event: GroupMessageEvent, logger: GenericLogger):
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
    image = await maker.make(
        msg.data,
        use_imgs=cfgloader.config.allow_image,
    )
    if image is None:
        await adapter.send_reply("目标消息中没有支持引用的元素")
        return
    imagebytes = image.getvalue()
    imageb64 = "base64://" + base64.b64encode(imagebytes).decode("utf-8")
    await adapter.send(ImageSegment(file=imageb64))
    if not (path := cfgloader.config.saveto):
        return
    file = os.path.join(
        path,
        f"{time.strftime("%Y%m%d-%H%M%S", time.localtime())}_{sender.user_id}_{event.group_id}.png",
    )
    async with aiofiles.open(file, "wb+") as fp:
        await fp.write(imagebytes)
    logger.info(f"quote saved as {file}")
