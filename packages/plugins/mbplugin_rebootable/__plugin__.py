import asyncio
import contextlib
import json
import random
import time
from pathlib import Path
from typing import TypedDict

from lemony_checkers import get_checker_factory_wrapper
from lemony_settings import BaseSettings, require
from lemony_storage_helper.files import configured_data_path
from lemony_utils.help import Command, register_help
from melobot import PluginInfo, PluginPlanner, on_command
from melobot.bot import Bot, BotLifeSpan, get_bot
from melobot.protocols.onebot.v11.adapter import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent


class RebootablePluginConfig(BaseSettings):
    # 于是默认是只有 owner 能够操作
    allow_admins: bool = False
    reboot_command: str = "重启"
    poweroff_command: str = "关机"
    # pydantic 会为每个实例复制默认值, 可变默认值在这里是安全的
    sayings_on_poweroff: list[str] = [  # noqa: RUF012
        "下班啦~",
        "拜拜~",
        "再见~",
    ]
    sayings_on_reboot: list[str] = [  # noqa: RUF012
        "待会儿见w",
        "正在重启, 请坐和放宽...",
    ]
    # 相对 data root; 旧配置里写的 "data/reboot_info.json" 也指向同一个文件
    reboot_info_path: str = "reboot_info.json"


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

_who = "owner 与 bot 管理员" if cfgloader.value.allow_admins else "owner"
register_help(
    PLUGIN_IDENTIFIER,
    title="重启",
    summary=f"重启 / 关闭 bot, 仅 {_who} 可用",
    aliases=["rebootable"],
    commands=[
        Command(
            f".{cfgloader.value.reboot_command}",
            "重启 bot, 完成后在原会话报告耗时",
            admin_only=True,
        ),
        Command(f".{cfgloader.value.poweroff_command}", "关闭 bot", admin_only=True),
    ],
)
checker_factory = get_checker_factory_wrapper(
    plugin_name=PLUGIN_IDENTIFIER,
)


def _privileged_checker():
    """重启/关机这类操作默认只有 owner 能触发, allow_admins 打开后管理员也可以."""
    if cfgloader.value.allow_admins:
        return checker_factory.get_admin_checker()
    return checker_factory.get_owner_checker()


@plugin.use
@on_command(
    ".",
    " ",
    [cfgloader.value.poweroff_command],
    checker=_privileged_checker(),
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
    checker=_privileged_checker(),
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
    await asyncio.to_thread(_write_reboot_info, reboot_info)
    await bot.restart()


def _reboot_info_path() -> Path:
    return configured_data_path(cfgloader.value.reboot_info_path, mkdir_parent=True)


def _write_reboot_info(info: RebootInfo) -> None:
    with open(_reboot_info_path(), "w+", encoding="utf-8") as fp:
        json.dump(info, fp)


def _read_reboot_info() -> RebootInfo | None:
    path = _reboot_info_path()
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


@bot.on_started
async def startup_check(adapter: Adapter):
    path = _reboot_info_path()
    if not await asyncio.to_thread(path.is_file):
        return
    try:
        info = await asyncio.to_thread(_read_reboot_info)
        if info is None:
            return
        start_time = bot.get_hook_evoke_time(BotLifeSpan.STARTED)
        interval = (start_time if start_time > 0 else time.time()) - info["time"]
        await adapter.send_custom(
            f"重启已完成, 耗时 {interval:.3f}s",
            user_id=info["uid"],
            group_id=info["gid"],
        )
    finally:
        with contextlib.suppress(OSError):
            path.unlink()
