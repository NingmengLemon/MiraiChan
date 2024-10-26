import atexit
import hashlib
import re
from melobot import Plugin, send_text, get_bot, get_logger
from melobot.handle import stop, bypass
from melobot.protocols.onebot.v11.adapter.event import MessageEvent, MetaEvent
from melobot.protocols.onebot.v11.adapter.segment import (
    AtSegment,
    TextSegment,
    ReplySegment,
)
from melobot.protocols.onebot.v11 import (
    on_command,
    on_meta,
    on_message,
    ParseArgs,
    Adapter,
)
from melobot.protocols.onebot.v11.handle import Args
from melobot.protocols.onebot.v11.utils import CmdArgFormatter
from melobot.ctx import Context
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata


class EroMoncakConfigDef(BaseModel):
    user_alias: dict[int, str] = {}
    match_regex: str = r"^[好][色涩瑟][情]?$"


logger = get_logger()
# cfgctx = Context[ConfigLoader[EroMoncakConfigDef]](
#     "eroconfig", RuntimeError, "未初始化就试图操作配置"
# )
config = ConfigLoader[EroMoncakConfigDef]()


@on_meta()
async def lazy_init(event: MetaEvent, adapter: Adapter):
    # config = cfgctx.try_get()
    # if not config:
    #     config = ConfigLoader[EroMoncakConfigDef]()
    #     cfgctx.add(config)
    if config.is_ready:
        await bypass()
    if event.meta_event_type == "lifecycle" and event.is_connect():
        bot = get_bot()
        login_info = await (await adapter.with_echo(adapter.get_login_info)())[0]
        uid = login_info.data["user_id"]
        config.set_config(
            ConfigLoaderMetadata(
                model=EroMoncakConfigDef,
                filename=f"eromoncak-{hashlib.md5(f"{bot.name}{uid}".encode("utf-8")).hexdigest()}.json",
            ),
        )
        config.load_config()
        atexit.register(config.save_config)
        logger.info("EroMoncak is ready for love")
    else:
        await stop()


@on_message()
async def say_noero(event: MessageEvent):
    # config = cfgctx.get().config
    if re.search(config.config.match_regex, event.text):
        sender = event.sender
        if sender.user_id and (alias := config.config.user_alias.get(sender.user_id)):
            await send_text(f"涩{alias}")
        else:
            await send_text("不许涩涩")


@on_command(
    ".",
    " ",
    "setalias",
    fmtters=[
        CmdArgFormatter(str),
        CmdArgFormatter(default=0),
    ],
)
async def set_alias(event: MessageEvent, adapter: Adapter, args: ParseArgs = Args()):
    await bypass()


class EroMoncak(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = [lazy_init, say_noero, set_alias]
