import atexit
from melobot.plugin import Plugin, AsyncShare, SyncShare
from melobot.protocols.onebot.v11 import on_command, Adapter
from melobot.protocols.onebot.v11.adapter.event import MessageEvent
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata


class AliasProviderConfigModel(BaseModel):
    user_alias: dict[int, str] = {}


cfgloader = ConfigLoader(
    ConfigLoaderMetadata(
        model=AliasProviderConfigModel,
        filename="alias_conf.json",
    )
)
cfgloader.load_config()
atexit.register(cfgloader.save_config)

share = SyncShare(
    "user_alias",
    reflector=lambda: cfgloader.config.user_alias,
)


@on_command(".", " ", "setalias")
def set_alias(
    event: MessageEvent,
    adapter: Adapter,
):
    pass


class AliasProvider(Plugin):
    version = "0.1.0"
    shares = (share,)
