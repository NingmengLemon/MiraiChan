import sys

from melobot import PluginPlanner, get_logger
from melobot.protocols.onebot.v11.handle import on_full_match
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory
import little_helper


EmergencyStop = PluginPlanner("0.1.0")


class EmStopConf(BaseModel):
    trigger_word: str = "!!!stop"
    triggered: bool = False


logger = get_logger()
cfgloader = ConfigLoader(
    ConfigLoaderMetadata(model=EmStopConf, filename="emergency_stop.json")
)
cfgloader.load_config()
if cfgloader.config.triggered:
    logger.critical("Emergency Stop triggered, reset needed")
    # 防止被自动重启，总之手动复位就行
    sys.exit(0)

little_helper.register(
    "EmergencyStop",
    {
        "cmd": cfgloader.config.trigger_word,
        "text": "紧急停止 Bot 程序，下次启动前需要手动复位\n*Owner Only*",
    },
)


@EmergencyStop.use
@on_full_match(
    cfgloader.config.trigger_word,
    checker=checker_factory.get_owner_checker(),
)
async def trigger():
    cfgloader.config.triggered = True
    cfgloader.save_config()
    logger.critical("Emergency Stop triggered, try quiting")
    sys.exit(0)
