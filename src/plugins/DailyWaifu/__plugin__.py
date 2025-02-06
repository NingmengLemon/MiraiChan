import asyncio

from melobot import get_bot
from melobot.plugin import PluginPlanner
from melobot.utils import async_interval
from melobot.handle import on_command
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import (
    AtSegment,
    TextSegment,
    ImageSegment,
)
from configloader import ConfigLoader, ConfigLoaderMetadata
import little_helper
from .core import WaifuManager
from .models import ConfigModel

DailyWaifu = PluginPlanner("0.1.0")
little_helper.register(
    "DailyWaifu", {"cmd": ".{waifu|今日老婆}", "text": "抽取今天的群U老婆"}
)
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


@DailyWaifu.use
@on_command(".", " ", ["今日老婆", "waifu"])
async def draw_waifu(event: GroupMessageEvent, adapter: Adapter):
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
