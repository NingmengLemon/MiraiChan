import os
import sys
import asyncio

from melobot import Bot
from melobot.log import Logger, LogLevel
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO

from pydantic import BaseModel

if "src" in os.listdir():
    sys.path.insert(0, "src")

if sys.platform != "win32":
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from ob11adapter_validation_patches import patch_all


class ForwWsIOConfigModel(BaseModel):
    url: str
    access_token: str | None = None


class GlobalConfigModel(BaseModel):
    forwwsio: ForwWsIOConfigModel
    debug: bool = False
    plugins: list[str] = []
    load_depth: int = 3


with open("./config.json", "rb") as fp:
    cfg = GlobalConfigModel.model_validate_json(fp.read())
debug = "--debug" in sys.argv or cfg.debug

logger = Logger(level=LogLevel.DEBUG if debug else LogLevel.INFO)
logger.debug("Config: " + cfg.model_dump_json(indent=4))
os.makedirs("data", exist_ok=True)

if __name__ == "__main__":
    bot = (
        Bot(
            "MiraiChan",
            logger=logger,
        )
        .add_io(ForwardWebSocketIO(**cfg.forwwsio.model_dump()))
        .add_adapter(patch_all(Adapter()))
    )
    bot.load_plugins(cfg.plugins, load_depth=cfg.load_depth)
    bot.run(debug=debug)
