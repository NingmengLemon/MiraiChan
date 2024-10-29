from typing import Any
from melobot import Plugin, get_bot, get_logger, GenericLogger
from melobot.plugin import SyncShare
from melobot.utils import RWContext
from melobot.protocols.onebot.v11 import Adapter, EchoRequireCtx, on_message


store: dict[str, Any] = {}
rwlock = RWContext()

bot = get_bot()
logger = get_logger()


@bot.on_loaded
async def get_onebot_login_info(adapter: Adapter) -> None:
    async with rwlock.write():
        echo = await (await adapter.with_echo(adapter.get_login_info)())[0]
        data = echo.data
        if echo.is_ok():
            store.update(data)
            logger.info("已获得 OneBot 账号信息")
        else:
            logger.warning("获取 OneBot 账号信息失败")


@bot.on_loaded
async def get_onebot_app_info(adapter: Adapter) -> None:
    async with rwlock.write():
        echo = await (await adapter.with_echo(adapter.get_version_info)())[0]
        data = echo.data
        if echo.is_ok():
            store.update(data)
            logger.info("已获得 Onebot 实现端信息")
        else:
            logger.warning("获取 Onebot 实现端信息失败")


async def get_info(name: str):
    async with rwlock.read():
        return store.get(name)


async def get_all_info():
    async with rwlock.read():
        return store.copy()


async def update_info(adapter: Adapter):
    await get_onebot_app_info(adapter)
    await get_onebot_login_info(adapter)


class OneBotInfoProvider(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    funcs = (get_info, get_all_info, update_info)
