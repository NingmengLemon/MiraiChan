import sys

from melobot import PluginPlanner, get_logger
from melobot.protocols.onebot.v11.handle import on_full_match
from pydantic import BaseModel

from configloader import ConfigLoader, ConfigLoaderMetadata
import checker_factory


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


@EmergencyStop.use
@on_full_match(
    cfgloader.config.trigger_word,
    checker=lambda e: e.sender.user_id == checker_factory.owner,
)
async def trigger():
    cfgloader.config.triggered = True
    cfgloader.save_config()
    logger.critical("Emergency Stop triggered, try quiting")
    sys.exit(0)
