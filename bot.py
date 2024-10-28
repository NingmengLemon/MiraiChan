import json
import sys
from typing import Any

from melobot import Bot
from melobot.log import Logger, LogLevel
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO

from pydantic import BaseModel


class ForwWsIOConfigModel(BaseModel):
    url: str
    access_token: str | None


class GlobalConfigModel(BaseModel):
    forwwsio: ForwWsIOConfigModel
    debug: bool = False
    plugins: list[str] = []


with open("./config.json", "rb") as fp:
    cfg = GlobalConfigModel.model_validate_json(fp.read())

if __name__ == "__main__":
    debug = "--debug" in sys.argv or cfg.debug
    if debug:
        print("config content:", cfg.model_dump_json(indent=4))
    bot = (
        Bot(
            "MiraiChan",
            logger=Logger(level=LogLevel.DEBUG if debug else LogLevel.INFO),
        )
        .add_io(ForwardWebSocketIO(**cfg.forwwsio.model_dump()))
        .add_adapter(Adapter())
    )
    bot.load_plugins(cfg.plugins)
    bot.run(debug=debug)
