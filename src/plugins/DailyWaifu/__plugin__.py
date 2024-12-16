import asyncio
from enum import Enum
from typing import Annotated
import base64

from melobot import get_bot, Event, stop
from melobot.plugin import PluginPlanner
from melobot.log import GenericLogger, get_logger
from melobot.di import Reflect
from melobot.utils import lock, async_interval, RWContext, unfold_ctx
from melobot.session import enter_session, Rule, suspend
from melobot.protocols.onebot.v11.handle import on_command, on_message, on_full_match
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import (
    AtSegment,
    TextSegment,
    Segment,
    ReplySegment,
    ImageSegment,
)
from configloader import ConfigLoader, ConfigLoaderMetadata
from .core import WaifuManager
from .models import ConfigModel
from .graph import render

DailyWaifu = PluginPlanner("0.1.0")
# inspired by kmua bot
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=ConfigModel, filename="waifu_conf.json")
)
cfgloader.load_config()
TIMEOUT = cfgloader.config.timeout
manager = WaifuManager(cfgloader.config.dburl)
bot = get_bot()

clear_task: asyncio.Task = None


@bot.on_loaded
async def _():
    global clear_task
    clear_task = async_interval(
        lambda: asyncio.to_thread(manager.clear_expired_dwr), 60 * 60 * 24
    )


@bot.on_stopped
async def _():
    if clear_task:
        clear_task.cancel()


class MarryRule(Rule[GroupMessageEvent]):
    async def compare(self, e1, e2):
        return await super().compare(e1, e2)


mrule = MarryRule()


class MarryStage(Enum):
    NOT_PROPOSED = 1
    NOT_CONFIRMED = 2
    CONFIRMED = 3
    REJECTED = 4


class MarryKw:
    propose = ("结婚", "结芬")
    accept = ("同意", "好", "愿意")
    reject = ("拒绝", "不要", "不")


@on_message()
@unfold_ctx(lambda: enter_session(mrule))
async def marry(
    event: Annotated[GroupMessageEvent, Reflect()],
    adapter: Annotated[Adapter, Reflect()],
    logger: GenericLogger,
):
    raise NotImplementedError()


@DailyWaifu.use
@on_command(".", " ", ["今日老婆", "waifu"])
async def draw_waifu(event: GroupMessageEvent, adapter: Adapter, logger: GenericLogger):
    me = event.sender
    if m := manager.query_mrels(event.group_id, a=me.user_id, b=None):
        await adapter.send_reply(
            [
                TextSegment("你和 "),
                AtSegment(m[0].a if m[0].b == me.user_id else m[0].b),
                TextSegment(" 已经结芬了噢"),
            ]
        )
        return
    if manager.query_dwrels(event.group_id, src=me.user_id, dst=None):
        await adapter.send_reply("你今天已经抽过了噢w")
        return
    usersecho = await (
        await adapter.with_echo(adapter.get_group_member_list)(event.group_id)
    )[0]
    if (users := usersecho.data) is None:
        await adapter.send_reply("获取群成员列表失败")
        return
    waifu = manager.draw_waifu(event.group_id, users)
    if waifu is None:
        await adapter.send_reply("已经没有可以当作老婆的群u了ww")
        return
    manager.add_waifu_rel(event.group_id, src=me.user_id, dst=waifu["user_id"])
    await adapter.send_reply(
        [
            TextSegment("你今天的老婆是 @{nickname} ！".format(**waifu)),
            ImageSegment(
                file=f"https://q1.qlogo.cn/g?b=qq&nk={waifu['user_id']}&s=640"
            ),
        ]
    )


@on_command(".", " ", ["离婚", "离芬", "divorce"])
async def divorce(
    event: Annotated[GroupMessageEvent, Reflect()],
    adapter: Annotated[Adapter, Reflect()],
):
    if _ := event.get_segments(ReplySegment):
        msg_id = _[0].data["id"]
        msg = await (await adapter.with_echo(adapter.get_msg)(msg_id))[0]
        if not msg.data:
            await adapter.send_reply("目标消息数据获取失败")
            return
        exwaifu = msg.data["sender"].user_id
    elif _ := event.get_segments(AtSegment):
        exwaifu = _[0].data["qq"]
        if exwaifu == "all":
            await adapter.send_reply("需要指定一个具体的群U")
            return
    else:
        await adapter.send_reply("需要指定目标")
        return

    if m := manager.query_mrels(event.group_id, event.user_id, None):
        if (m[0].a if m[0].b == event.user_id else m[0].b) == exwaifu:
            manager.divorce(event.group_id, event.user_id, exwaifu)
            await adapter.send_reply(
                [
                    AtSegment(event.user_id),
                    TextSegment(" 和 "),
                    AtSegment(exwaifu),
                    TextSegment(" 离芬了w，残念喵"),
                ]
            )
        else:
            await adapter.send_reply("这不是你的老婆ww")
    else:
        await adapter.send_reply("你还没有群老婆ww")


@on_command(".", " ", ["老婆关系图", "waifu_graph"])
async def show_waifu(event: GroupMessageEvent, adapter: Adapter, logger: GenericLogger):
    dw, mr = manager.dump(event.group_id)
    if not dw:
        await adapter.send_reply("本群中暂时没有可以画出的关系")
        return
    usersecho = await (
        await adapter.with_echo(adapter.get_group_member_list)(event.group_id)
    )[0]
    if (_ := usersecho.data) is None:
        logger.warning("获取群成员列表失败，图中将不会有额外信息")
    imgbytes = await render(_ or [], dw, mr)
    imageb64 = "base64://" + base64.b64encode(imgbytes).decode("utf-8")
    await adapter.send(ImageSegment(file=imageb64))
