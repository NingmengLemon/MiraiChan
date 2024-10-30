import json
import sys
from typing import Any

from melobot import Bot
from melobot.log import Logger, LogLevel
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO

from pydantic import BaseModel


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

if __name__ == "__main__":
    bot = (
        Bot(
            "MiraiChan",
            logger=logger,
        )
        .add_io(ForwardWebSocketIO(**cfg.forwwsio.model_dump()))
        .add_adapter(Adapter())
    )
    bot.load_plugins(cfg.plugins, load_depth=cfg.load_depth)
    bot.run(debug=debug)
