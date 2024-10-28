import atexit
from melobot import get_logger
from melobot.plugin import Plugin, AsyncShare, SyncShare
from melobot.protocols.onebot.v11 import on_message, on_start_match, Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from melobot.utils import RWContext
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata


class AliasProviderConfigModel(BaseModel):
    user_alias: dict[int, str] = {}


logger = get_logger()
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(
        model=AliasProviderConfigModel,
        filename="alias_conf.json",
    )
)
cfgloader.load_config()
atexit.register(cfgloader.save_config)
rwlock = RWContext()


@on_start_match(".setalias")
async def cmd_set_alias(
    event: MessageEvent,
    adapter: Adapter,
):
    text = event.text.strip()
    if len((args := text.split(maxsplit=1))) == 2 and (uid := event.user_id):
        alias = args[1]
        await set_alias(uid, alias)
        await adapter.send_reply(f"已将你的别称设为 {alias} ！")
    else:
        await del_alias(uid)
        await adapter.send_reply("已将你的别称删除w")


async def get_alias(uid: int):
    async with rwlock.read():
        return cfgloader.config.user_alias.get(uid)


async def set_alias(uid: int, alias: str):
    async with rwlock.write():
        cfgloader.config.user_alias[uid] = alias


async def if_alias_exists(alias: str):
    async with rwlock.read():
        return alias in cfgloader.config.user_alias.values()


async def del_alias(uid: int):
    async with rwlock.write():
        if uid in cfgloader.config.user_alias:
            del cfgloader.config.user_alias[uid]
            return True
        return False


class AliasProvider(Plugin):
    version = "0.1.0"
    funcs = (get_alias, set_alias, if_alias_exists, del_alias)
    flows = (cmd_set_alias,)
