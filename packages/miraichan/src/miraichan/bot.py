import asyncio
import os
import sys

from melobot import Bot, add_import_fallback
from melobot.log import Logger, LogLevel
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO

from .config import GlobalConfigModel

if "src" in os.listdir():
    sys.path.insert(0, "src")

if sys.platform == "win32":
    add_import_fallback("_sqlite3")
else:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from lemony_utils.validation_patches.ob11 import patch_all

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
