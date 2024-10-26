import json
import sys
from typing import Any

from melobot import Bot
from melobot.log import Logger, LogLevel
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO


debug = "--debug" in sys.argv

with open("./config.json", "r", encoding="utf-8") as fp:
    cfg: dict[str, Any] = json.load(fp)
if debug:
    print("config content:", cfg)

if __name__ == "__main__":
    bot = (
        Bot(
            "MiraiChan",
            logger=Logger(
                level=LogLevel.DEBUG if debug else LogLevel.INFO
            ),
        )
        .add_io(ForwardWebSocketIO(**cfg["forwwsio"]))
        .add_adapter(Adapter())
    )
    bot.load_plugins(cfg.get("plugins", []))
    bot.run(debug=debug)
