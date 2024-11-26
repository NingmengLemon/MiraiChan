import asyncio
from enum import Enum
import json
from typing import Annotated
import time

from melobot import get_bot, Event, stop
from melobot.plugin import Plugin
from melobot.log import GenericLogger, get_logger
from melobot.di import Reflect
from melobot.utils import lock, async_interval, if_not, unfold_ctx
from melobot.session import enter_session, Rule, suspend
from melobot.protocols.onebot.v11.handle import on_command
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from melobot.protocols.onebot.v11.adapter.segment import (
    AtSegment,
    TextSegment,
    Segment,
    ReplySegment,
)

from configloader import ConfigLoader, ConfigLoaderMetadata
from .core import WaifuManager, RelExistsError, RelNotExistsError
from .models import ConfigModel

# inspired by kmua bot
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=ConfigModel, filename="waifu_conf.json")
)
cfgloader.load_config()
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


def get_waifu_rule(me: int, waifu: int):
    async def meth(e1: Event, e2: Event):
        if not (
            isinstance(e1, GroupMessageEvent) and isinstance(e2, GroupMessageEvent)
        ):
            return False
        return e1.group_id == e2.group_id and (e2.user_id == me or e2.user_id == waifu)

    return Rule.new(meth)


class WaifuRule(Rule[GroupMessageEvent]):
    def __init__(self, me: int, waifu: int):
        super().__init__()
        self.me = me
        self.waifu = waifu

    async def compare(self, e1, e2):
        result = e1.scope == e2.scope
        # result = e1.group_id == e2.group_id and (
        #     e2.user_id == self.me or e2.user_id == self.waifu
        # )
        get_logger().debug(f"compare() 被调用力，{result=}")
        return result


class MarryStage(Enum):
    NOT_PROPOSED = 1
    NOT_CONFIRMED = 2
    CONFIRMED = 3
    REJECTED = 4


@on_command(".", " ", ["今日老婆", "waifu"])
async def draw_waifu(
    event: Annotated[GroupMessageEvent, Reflect()],
    adapter: Annotated[Adapter, Reflect()],
    logger: GenericLogger,
):
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
    await adapter.send_reply("你今天的老婆是「{nickname}」！".format(**waifu))

    async with enter_session(WaifuRule(me.user_id, waifu["user_id"])):
        logger.debug("已进入结芬会话")
        stage = MarryStage.NOT_PROPOSED
        while True:
            if not (await suspend(60 * 10)):
                logger.debug("结芬会话超时，已退出")
                await stop()
            logger.debug("结芬会话收到消息，进行解析")
            match event.text.strip():
                case "结芬" | "结婚":
                    if event.user_id == me.user_id and stage == MarryStage.NOT_PROPOSED:
                        stage = MarryStage.NOT_CONFIRMED
                        await adapter.send_reply(
                            [AtSegment(waifu["user_id"]), TextSegment("，你愿意吗（）")]
                        )
                        logger.debug("结芬会话进入确认环节")
                case "同意" | "好" | "愿意":
                    if (
                        event.user_id == waifu["user_id"]
                        and stage == MarryStage.NOT_CONFIRMED
                    ):
                        stage = MarryStage.CONFIRMED
                        manager.add_waifu_rel(
                            event.group_id, me.user_id, waifu["user_id"]
                        )
                        await adapter.send(
                            [
                                TextSegment("好耶！祝贺群里又多了一对ww "),
                                AtSegment(me.user_id),
                                AtSegment(waifu["user_id"]),
                            ]
                        )
                        logger.debug("已确认结芬")
                        await stop()
                case "拒绝" | "不要" | "不":
                    if (
                        event.user_id == waifu["user_id"]
                        and stage == MarryStage.NOT_CONFIRMED
                    ):
                        stage = MarryStage.REJECTED
                        await adapter.send(
                            [AtSegment(me.user_id), TextSegment(" 呜呜被拒绝惹（）")]
                        )
                        logger.debug("已拒绝结芬")
                        await stop()
                case _:
                    logger.debug(f"消息文本{event.text}未命中任何指令，进入下一轮")


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
                    TextSegment("你和 "),
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
    await adapter.send_reply(str(manager.dump(event.group_id)))


class DailyWaifu(Plugin):
    author = "LemonyNingmeng"
    version = "0.1.0"
    flows = (draw_waifu, divorce, show_waifu)
