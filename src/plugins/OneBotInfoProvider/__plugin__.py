from typing import Any
import json

from melobot import PluginPlanner, get_bot, get_logger
from melobot.protocols.onebot.v11 import (
    Adapter,
    on_command,
    on_meta,
)
from melobot.protocols.onebot.v11.adapter.event import HeartBeatMetaEvent

from ... import checker_factory


store: dict[str, Any] = {}

bot = get_bot()
logger = get_logger()


@bot.on_loaded
async def get_onebot_login_info(adapter: Adapter) -> None:
    echo = await (await adapter.with_echo(adapter.get_login_info)())[0]
    if echo.data:
        store.update(echo.data)
        logger.info("已获得 OneBot 账号信息")
    else:
        logger.warning("获取 OneBot 账号信息失败")


@bot.on_loaded
async def get_onebot_app_info(adapter: Adapter) -> None:
    echo = await (await adapter.with_echo(adapter.get_version_info)())[0]
    if echo.data:
        store.update(echo.data)
        logger.info("已获得 Onebot 实现端信息")
    else:
        logger.warning("获取 Onebot 实现端信息失败")


def get_info():
    return store.copy()


async def update_info(adapter: Adapter):
    await get_onebot_app_info(adapter)
    await get_onebot_login_info(adapter)


OneBotInfoProvider = PluginPlanner("0.1.0", funcs=[get_info, update_info])


@OneBotInfoProvider.use
@on_meta()
async def auto_update_meta(event: HeartBeatMetaEvent):
    store["status"] = event.status.raw.copy()
    store["time"] = event.time


@OneBotInfoProvider.use
@on_command(
    ".", " ", "botinfo", checker=lambda e: e.sender.user_id == checker_factory.owner
)
async def echo_info(adapter: Adapter):
    await adapter.send_reply(
        json.dumps(
            get_info(),
            ensure_ascii=False,
            indent=4,
        )
    )
