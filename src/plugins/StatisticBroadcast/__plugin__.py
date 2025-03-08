import asyncio
import json
import time
import uuid
from datetime import timedelta
from typing import cast

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.calendarinterval import CalendarIntervalTrigger
from melobot import get_bot, get_logger
from melobot.handle import on_command
from melobot.handle.base import flow_to
from melobot.handle.register import FlowDecorator
from melobot.plugin import PluginPlanner
from melobot.protocols.onebot.v11.adapter import Adapter, EchoRequireCtx
from melobot.protocols.onebot.v11.adapter.event import PrivateMessageEvent
from melobot.utils import lock
from melobot.utils.parse.cmd import CmdArgs
from sqlmodel import func, select

from configloader import ConfigLoader, ConfigLoaderMetadata
from lemony_utils.botutils import PrefilledCmdArgFmtter
from lemony_utils.time import get_time_period_start
from recorder_models import Message

from .. import Recorder
from .model import CfgModel, PrivateReg

cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=CfgModel, filename="statistic_conf.json")
)
cfgloader.load_config()

plugin = PluginPlanner("0.1.0")
scheduler = AsyncIOScheduler()
job_table: dict[str, Job] = {}

bot = get_bot()
logger = get_logger()


@bot.on_started
async def init():
    scheduler.start()
    for jobdata in cfgloader.config.private_registrations:
        add_job(jobdata)


@bot.on_stopped
async def stop():
    scheduler.shutdown()
    cfgloader.save_config()


AVAILABLE_CITPARAMS = ["years", "months", "weeks", "days", "hour", "minute", "second"]
TIMESTR_FORMAT = "%Y-%m-%d %H:%M:%S"


def add_job(data: PrivateReg):
    # 添加进 scheduler
    job = scheduler.add_job(
        send_stat,
        CalendarIntervalTrigger(
            **{k: v for k, v in data.items() if k in AVAILABLE_CITPARAMS}
        ),
        kwargs={"group_id": data["group_id"], "user_id": data["user_id"]},
        id=data["id"],
    )
    job_table[data["id"]] = job


@lock()
async def send_stat(group_id: int, user_id: int):
    adapter = bot.get_adapter(Adapter)
    if adapter is None:
        logger.error("没能获取到 OneBot11 适配器")
        return
    adapter = cast(Adapter, adapter)
    result: dict[int, int] = {}
    member_list = await (
        await adapter.with_echo(adapter.get_group_member_list)(group_id=group_id)
    )[0]
    end_time = get_time_period_start("day", time.time())
    start_time = end_time - timedelta(days=1)
    base_stmt = (
        select(func.count())
        .select_from(Message)
        .where(
            Message.group_id == group_id,
            Message.timestamp >= start_time.timestamp(),
            Message.timestamp <= end_time.timestamp(),
        )
    )
    async with Recorder.get_session() as session:
        if member_list.data:
            for member in member_list.data:
                uid = member["user_id"]
                count = (
                    await session.exec(
                        base_stmt.where(Message.sender_id == member["user_id"])
                    )
                ).one()
                if count > 0:
                    result[uid] = count
    result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    msg_base = (
        f"{start_time.strftime(TIMESTR_FORMAT)} ~ {end_time.strftime(TIMESTR_FORMAT)}"
        f"\ngroup={group_id}\ntotal={sum(result.values())}\n"
    )
    msg_full = msg_base + result_json
    msg_short = msg_base + "null"
    with EchoRequireCtx().unfold(True):
        echo = await (await adapter.send_custom(msg_full, user_id=user_id))[0]
        if not echo or not echo.data:
            echo = await (await adapter.send_custom(msg_short, user_id=user_id))[0]
        if not echo or not echo.data:
            logger.warning(f"未能成功向 {user_id} 汇报 {group_id} 的统计数据")
    await asyncio.sleep(2)  # 故意的w


@plugin.use
@on_command(
    ".",
    " ",
    "statsubsc",
    fmtters=[
        PrefilledCmdArgFmtter(
            validate=lambda x: x in ["reg", "unreg", "list"],
            src_desc="二级指令",
            src_expect="`reg` / `unreg` / `list`",
        ),
        PrefilledCmdArgFmtter(
            convert=int,
            validate=lambda x: x >= 100000 or x == -1,
            src_desc="要订阅统计的群号",
            src_expect="群号",
            default=-1,
        ),
    ],
    checker=lambda e: isinstance(e, PrivateMessageEvent) and e.is_friend(),
)
async def shunt(adapter: Adapter, args: CmdArgs):

    if args.vals[0] in ("reg", "unreg"):
        if args.vals[1] == -1:
            await adapter.send_reply("需要指定群号")
            return
        if not await check_group_id(adapter, args.vals[1]):
            await adapter.send_reply("指定的群号不可用")
            return
    match args.vals[0]:
        case "reg":
            await flow_to(register)
        case "unreg":
            await flow_to(unregister)
        case "list":
            await flow_to(listreg)


async def check_group_id(adapter: Adapter, group_id: int):
    group_list_echo = await (await adapter.with_echo(adapter.get_group_list)())[0]
    if not group_list_echo.data:
        return False
    for group in group_list_echo.data:
        if group["group_id"] == group_id:
            break
    else:
        return False
    return True


@FlowDecorator()
async def listreg(event: PrivateMessageEvent, adapter: Adapter):
    regs = [
        reg
        for reg in cfgloader.config.private_registrations
        if reg["user_id"] == event.user_id
    ]
    if regs:
        await adapter.send_reply(
            "当前已订阅: \n"
            + "\n".join(
                [
                    f"{reg["group_id"]} at {reg['hour']:02d}:{reg['minute']:02d}/{reg['days']}d"
                    for reg in regs
                ]
            )
        )
    else:
        await adapter.send_reply("当前还没有订阅任何群聊")


@FlowDecorator()
async def register(event: PrivateMessageEvent, adapter: Adapter, args: CmdArgs):
    group_id: int = args.vals[1]
    for reg in cfgloader.config.private_registrations:
        if reg["group_id"] == group_id and reg["user_id"] == event.user_id:
            await adapter.send_reply("你已订阅过此群聊了")
            return
    jobdata: PrivateReg = {
        "id": str(uuid.uuid4()),
        "group_id": group_id,
        "user_id": event.user_id,
        "days": 1,
        "hour": 0,
        "minute": 1,
        # 其实汇报时间都可以自定义啊 但是懒得写w
    }
    cfgloader.config.private_registrations.append(jobdata)
    add_job(jobdata)
    await adapter.send_reply(f"已成功订阅群聊 {group_id} 的每日统计")


@FlowDecorator()
async def unregister(event: PrivateMessageEvent, adapter: Adapter, args: CmdArgs):
    group_id: int = args.vals[1]
    for idx, reg in enumerate(cfgloader.config.private_registrations):
        if reg["group_id"] == group_id and reg["user_id"] == event.user_id:
            jid = reg["id"]
            job = job_table.pop(jid, None)
            if job:
                job.remove()
            break
    else:
        await adapter.send_reply("你还没有订阅此群聊")
        return
    cfgloader.config.private_registrations.pop(idx)
    await adapter.send_reply("已退订此群聊")
