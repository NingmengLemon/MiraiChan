import asyncio
from io import BytesIO
from melobot import Plugin, send_text, get_logger
from melobot.protocols.onebot.v11.adapter.event import (
    GroupMessageEvent,
    _GroupMessageSender,
)
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment
from melobot.protocols.onebot.v11.adapter.echo import (
    GetMsgEcho,
    GetGroupHonorInfoEcho,
)
from melobot.protocols.onebot.v11 import on_command, Adapter
from pydantic import BaseModel
from PIL import Image

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


async def make_quote(msg: GetMsgEcho, avatar: str | None = None):
    avatar_img = await fetch_image(avatar)
    return await run_as_async(make_image, (avatar_img, msg))


async def fetch_image(url: str | None):
    if url:
        try:
            async with async_http(url, "get", headers=http_headers) as resp:
                resp.raise_for_status()
                return BytesIO(await resp.content.read())
        except Exception as e:
            logger.error(f"error while get img, error={e}")


def get_avatar_from_honor(honor: GetGroupHonorInfoEcho, user_id: int) -> None | str:
    if not honor.data:
        return None
    avail_field = (
        "talkative_list",
        "performer_list",
        "legend_list",
        "strong_newbie_list",
        "emotion_list",
    )
    for key, val in honor.data.values():
        if key in avail_field:
            for user in val:
                if user["user_id"] == user_id:
                    return user["avatar"]
    return None


@on_command(".", " ", ["q", "quote"])
async def quote(adapter: Adapter, event: GroupMessageEvent):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
    else:
        await adapter.send_reply("需要指定目标消息")
        return
    msg, honor = await asyncio.gather(
        (await adapter.with_echo(adapter.get_msg)(msg_id))[0],
        (await adapter.with_echo(adapter.get_group_honor_info)(event.group_id, "all"))[
            0
        ],
    )
    image = await make_quote(msg, get_avatar_from_honor(honor, msg.sender.user_id))
    await adapter.send_image(
        f"[{msg.sender.title or msg.sender.nickname}的怪话]", raw=image.read()
    )


class Quoter(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (quote,)
