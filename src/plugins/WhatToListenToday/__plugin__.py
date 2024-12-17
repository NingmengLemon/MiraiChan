import atexit
import time
from typing import Literal

from melobot import PluginPlanner, PluginInfo
from melobot.log import GenericLogger
from melobot.utils import RWContext
from melobot.protocols.onebot.v11.handle import (
    on_full_match,
    on_start_match,
    on_command,
)
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent, MessageEvent
from melobot.protocols.onebot.v11.adapter import Adapter

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
import little_helper

from .models import WTLTConfig, DrawResp, StatusResp
from lemony_utils.templates import async_http

WhatToListen = PluginPlanner("0.1.0")
little_helper.register(
    "WhatToListenToday",
    {
        "cmd": ".{今天听什么|wtlt} [--filter <field1>:<value1>[;<field2>:<value2>;...]]",
        "text": "今天听……？",
    },
    {
        "cmd": ".{今天听什么|wtlt} {status|pause|resume|scan}",
        "text": "管理程序后端\n*Owner Only*",
    },
)

cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=WTLTConfig, filename="whattolisten_conf.json")
)
cfgloader.load_config()
access_token = cfgloader.config.access_token
server = cfgloader.config.server.rstrip("/")
share_host = cfgloader.config.share_host.rstrip("/")
headers = {"Authorization": f"Bearer {access_token}"}
atexit.register(cfgloader.save_config)
draw_cdtable: dict[int, float] = {}
record_lock = RWContext()


def wrapped_asynchttp(point: str, **kwargs):
    return async_http(server + point, method="get", headers=headers, **kwargs)


def gen_reply(data: DrawResp):
    reply = ["今天听 "]
    artists = data["artists"]
    match len(artists):
        case 0:
            pass
        case 1:
            reply.append(f"{artists[0]} 的")
        case 2:
            reply += [artists[0], " 和 ", artists[1], " 的"]
        case _:
            reply += ["、".join(artists[:-1]), " 和 ", artists[-1], " 的"]
    if title := data["title"]:
        reply.append(f"「{title}」")
    elif artists:
        reply.append("歌")
    else:
        reply.append("这首歌")
    reply.append("！\n")
    if (album := data["album"]) and (album != title):
        reply.append(f"出自专辑「{album}」\n")
    if dura := data["duration"]:
        reply.append(f"时长 {dura//60:.0f} 分 {dura%60:0>2.0f} 秒\n")
    if cfgloader.config.share_link:
        reply += [
            "如果你在电砖内网，那么现在就可以听w\n",
            share_host,
            data["player"],
        ]
    return "".join(reply)


_ConstrainDict = dict[Literal["artist", "album", "title"], str]
_supported_constrains = {"artist", "album", "title"}


def parse_constrains(cmd: str) -> _ConstrainDict:
    result = {}
    for statement in cmd.removeprefix("filter").split(";"):
        if len(_ := statement.split("=", maxsplit=1)) == 2:
            field, value = _[0].strip().lower(), _[1].strip()
            if field in _supported_constrains:
                result[field] = value
    return result


@WhatToListen.use
@on_start_match([".wtlt", ".今天听什么"])
async def entrance(
    adapter: Adapter,
    event: MessageEvent,
):
    cmd = event.text
    args = cmd.split(maxsplit=1)[1:]
    if not args or args[0].startswith("--filter"):
        await draw(
            adapter, event, constrains=(parse_constrains(args[0]) if args else None)
        )
    else:
        await opts(adapter, event, args[0])


async def draw(
    adapter: Adapter,
    event: GroupMessageEvent,
    constrains: _ConstrainDict | None = None,
):
    async with record_lock.read():
        if (
            draw_cdtable.get(event.sender.user_id, 0) > time.time()
            and event.sender.user_id != checker_factory.OWNER
        ):
            await adapter.send_reply("请至少听完这首歌……！")
            return
    try:
        async with wrapped_asynchttp("/draw", params=constrains) as resp:
            data = await resp.json()
            if resp.status != 200:
                await adapter.send_reply(
                    f"后端响应状态异常：\ncode={resp.status}, data={data}"
                )
                return
    except Exception as e:
        await adapter.send_reply(f"向后端请求数据时出错：{e}")
        return
    data: DrawResp
    async with record_lock.write():
        draw_cdtable[event.sender.user_id] = time.time() + data["duration"]
    await adapter.send_reply(gen_reply(data))


def gen_status(data: StatusResp):
    return """后端工作状态：{status}
库存总计：{count}
已运行：{online:.2f}秒""".format(
        **data
    )


async def opts(adapter: Adapter, event: MessageEvent, cmd: str):
    if event.user_id != checker_factory.OWNER:
        await adapter.send_reply("无权使用此指令")
        return
    try:
        match cmd:
            case "status":
                async with wrapped_asynchttp("/status") as resp:
                    if resp.status == 200:
                        await adapter.send_reply(gen_status(await resp.json()))
                    else:
                        await adapter.send_reply(f"异常的后端响应：{await resp.json()}")
            case "pause" | "resume" | "scan":
                async with wrapped_asynchttp(f"/{cmd}") as resp:
                    await adapter.send_reply(f"后端响应：{await resp.json()}")
            case _:
                await adapter.send_reply("未知的二级指令喵")
    except Exception as e:
        await adapter.send_reply(f"向后端发送指令时出错：{e}")
