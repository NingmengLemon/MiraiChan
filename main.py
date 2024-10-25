import json
from typing import Any

from melobot import Bot
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO

with open("./config.json", "r", encoding="utf-8") as fp:
    cfg: dict[str, Any] = json.load(fp)


if __name__ == "__main__":
    bot = (
        Bot(__name__)
        .add_io(ForwardWebSocketIO(**cfg["forwwsio"]))
        .add_adapter(Adapter())
    )
    for plugin in cfg.get("plugins", []):
        pass
    bot.run(cfg.get("debug", False))
