import base64
from io import BytesIO
import time
import os
from typing import cast

from melobot import Plugin, get_logger
from melobot.protocols.onebot.v11.adapter.echo import Echo
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import ReplySegment, ImageSegment
from melobot.protocols.onebot.v11 import on_command, Adapter
from pydantic import BaseModel, Field

from configloader import ConfigLoader, ConfigLoaderMetadata
from extended_actions.lagrange import (
    UploadGroupFileAction,
    GetGroupRootFilesAction,
    CreateGroupFileFolderAction,
)

from .maker import QuoteMaker
from .tmpfilehost import TmpfileHost

qqface_to_emoji_map = {
    
}


class UploaderCfg(BaseModel):
    tmpfilehost: str | None = None
    access_token: str = "哼哼哼啊啊"
    enable: bool = False
    folder: str = "群U的怪话"


class QuoteConfig(BaseModel):
    emoji_cdn: str | None = None
    font: str = "data/fonts/NotoSansSC-Medium.ttf"
    mask: str = "data/quote_mask.png"
    uploader: UploaderCfg = Field(default_factory=UploaderCfg)


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
tfh = (
    TmpfileHost(
        endpoint=cfgloader.config.uploader.tmpfilehost,
        access_token=cfgloader.config.uploader.access_token,
    )
    if cfgloader.config.uploader.tmpfilehost and cfgloader.config.uploader.enable
    else None
)
upload_folder = cfgloader.config.uploader.folder


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
    # do upload
    return
    if not tfh:
        return
    logger.info(
        f"uploading quote from {sender.user_id}({sender.nickname}) in group {event.group_id}"
    )
    logger.debug(f"ensuring folder existence: {upload_folder}")
    folder_id = None
    if (rootdirs := await list_group_rootdirs(adapter, event.group_id)) is None:
        logger.error("error when checking folder existence")
        return
    else:
        for folder in rootdirs["folders"]:
            if folder["folder_name"] == upload_folder:
                folder_id = folder["folder_id"]
                break
    if not folder_id:
        logger.info("target folder not exists, using rootdir")
        folder_id = "/"
        # logger.info("target folder not exists, try creating")
        # creation_result = cast(
        #     Echo,
        #     await (
        #         await adapter.with_echo(adapter.call_output)(
        #             CreateGroupFileFolderAction(
        #                 group_id=event.group_id, name=upload_folder, parent_id=None
        #             )
        #         )
        #     )[0],
        # )
    async with tfh.tmpsession(None, data=imagebytes) as rmtpath:
        result: Echo = await (
            await adapter.with_echo(adapter.call_output)(
                UploadGroupFileAction(
                    group_id=event.group_id,
                    file=rmtpath,
                    name=f"{time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())}_{sender.user_id}.png",
                    folder=upload_folder,
                )
            )
        )[0]
    logger.debug(f"upload result: {result}")
    if not result.ok:
        logger.warning("failed to upload")


async def list_group_rootdirs(adapter: Adapter, group_id: int):
    rootdirs = cast(
        Echo,
        await (
            await adapter.with_echo(adapter.call_output)(
                GetGroupRootFilesAction(group_id)
            )
        )[0],
    )
    if rootdirs.ok:
        return rootdirs.data
    else:
        return None


async def create_folder():
    pass


class Quoter(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (quote,)
