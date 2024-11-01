import atexit
from melobot import Plugin
from melobot.protocols.onebot.v11.handle import on_full_match
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory

import sys


class EmStopConf(BaseModel):
    triggered: bool = False


cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=EmStopConf, filename="emergency_stop.json")
)
cfgloader.load_config()
if cfgloader.config.triggered:
    # 防止被自动重启，总之手动复位就行
    sys.exit(0)


@on_full_match("!!!stop", checker=lambda e: e.sender.user_id == checker_factory.owner)
async def trigger():
    cfgloader.config.triggered = True
    cfgloader.save_config()
    sys.exit(0)


class EmStop(Plugin):
    version = "0.1.0"
    author = "LemonyNingmeng"
    flows = (trigger,)
