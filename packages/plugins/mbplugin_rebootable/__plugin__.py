import json
import os
import random
import time
from typing import TypedDict

from lemony_checkers import get_checker_factory_wrapper
from lemony_settings import BaseSettings, require
from melobot import PluginInfo, PluginPlanner, on_command
from melobot.bot import Bot, BotLifeSpan, get_bot
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent


class RebootablePluginConfig(BaseSettings):
    # 于是默认是只有 owner 能够操作
    allow_admins: bool = False
    reboot_command: str = "重启"
    poweroff_command: str = "关机"
    sayings_on_poweroff: list[str] = [
        "下班啦~",
        "拜拜~",
        "再见~",
    ]
    sayings_on_reboot: list[str] = [
        "待会儿见w",
        "正在重启, 请坐和放宽...",
    ]
    reboot_info_path: str = "data/reboot_info.json"


bot = get_bot()
plugin = PluginPlanner(
    "0.1.0",
    info=PluginInfo(desc="让Bot可通过指令重启. 需要整个bot通过mb-cli启动."),
)


PLUGIN_IDENTIFIER = "mbplugin_rebootable"

cfgloader = require(
    model=RebootablePluginConfig,
    identifier=PLUGIN_IDENTIFIER,
)
cfgloader.load()
checker_factory = get_checker_factory_wrapper(
    plugin_name=PLUGIN_IDENTIFIER,
)


@plugin.use
@on_command(
    ".",
    " ",
    [cfgloader.value.poweroff_command],
    checker=checker_factory.get_owner_checker(),
)
async def stop_bot(adapter: Adapter, bot: Bot) -> None:
    await (await adapter.send(random.choice(cfgloader.value.sayings_on_poweroff)))[0]
    await bot.close()


class RebootInfo(TypedDict):
    time: float
    uid: int
    gid: int | None


@plugin.use
@on_command(
    ".",
    " ",
    [cfgloader.value.reboot_command],
    checker=checker_factory.get_owner_checker(),
)
async def restart_bot(event: MessageEvent, adapter: Adapter, bot: Bot):
    if not bot.is_restartable():
        await adapter.send_reply("当前启动方式不支持重启w")
        return
    await (await adapter.send(random.choice(cfgloader.value.sayings_on_reboot)))[0]
    reboot_info: RebootInfo = {
        "gid": event.group_id if isinstance(event, GroupMessageEvent) else None,
        "uid": event.user_id,
        "time": time.time(),
    }
    with open(cfgloader.value.reboot_info_path, "w+", encoding="utf-8") as fp:
        json.dump(reboot_info, fp)
    await bot.restart()


@bot.on_started
async def startup_check(adapter: Adapter):
    if not os.path.isfile(cfgloader.value.reboot_info_path):
        return
    try:
        with open(cfgloader.value.reboot_info_path, "r", encoding="utf-8") as fp:
            info: RebootInfo = json.load(fp)
        start_time = bot.get_hook_evoke_time(BotLifeSpan.STARTED)
        interval = (start_time if start_time > 0 else time.time()) - info["time"]
        await adapter.send_custom(
            f"重启已完成, 耗时 {interval:.3f}s",
            user_id=info["uid"],
            group_id=info["gid"],
        )
    finally:
        try:
            os.remove(cfgloader.value.reboot_info_path)
        except OSError:
            pass
