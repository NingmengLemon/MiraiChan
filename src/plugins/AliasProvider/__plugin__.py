import atexit
from melobot import get_logger
from melobot.plugin import PluginPlanner
from melobot.handle import on_start_match
from melobot.protocols.onebot.v11 import Adapter
from melobot.protocols.onebot.v11.adapter.event import GroupMessageEvent
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
import little_helper


class AliasProviderConfigModel(BaseModel):
    user_alias: dict[int, str] = {}
    length_limit: int = 20


logger = get_logger()
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(
        model=AliasProviderConfigModel,
        filename="alias_conf.json",
    )
)
cfgloader.load_config()
atexit.register(cfgloader.save_config)


def get_alias(uid: int):
    return cfgloader.config.user_alias.get(uid)


def set_alias(uid: int, alias: str | None):
    if alias is None:
        cfgloader.config.user_alias.pop(uid, None)
    else:
        cfgloader.config.user_alias[uid] = alias


def if_alias_exists(alias: str):
    return alias in cfgloader.config.user_alias.values()


AliasProvider = PluginPlanner("0.1.0", funcs=[set_alias, get_alias, if_alias_exists])
little_helper.register(
    "AliasProvider",
    {
        "cmd": ".setalias <alias>",
        "text": "设定Bot对你的称呼",
    },
)


@AliasProvider.use
@on_start_match(".setalias")
async def cmd_set_alias(
    event: GroupMessageEvent,
    adapter: Adapter,
):
    text = event.text.strip()
    if len((args := text.split(maxsplit=1))) == 2:
        alias = args[1]
        if len(alias) > cfgloader.config.length_limit:
            await adapter.send_reply(
                f"字数超出限制喵，当前限制 {cfgloader.config.length_limit} 字"
            )
        else:
            set_alias(event.user_id, alias)
            await adapter.send_reply(f"已将你的别称设为 「{alias}」 ！")
    else:
        set_alias(event.user_id, None)
        await adapter.send_reply("已经将你的别称删除了ww")
