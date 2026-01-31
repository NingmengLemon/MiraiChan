import asyncio
import os
import sys

from lemony_checkers import get_checker_global_settings
from lemony_settings import init_global_settings
from lemony_utils.validation_patches.ob11 import patch_all
from melobot import Bot, add_import_fallback
from melobot.log import Logger, LogLevel
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO

from .config import CONFIG_PATH, GlobalConfigModel
from .loader import resolve_plugin_path

if sys.platform == "win32":
    add_import_fallback("_sqlite3")
else:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def main():
    if not CONFIG_PATH.exists():
        print("配置文件 config.json 不存在, 无法启动 Miraichan.")
        print("预期的位置: ", CONFIG_PATH.resolve())
        sys.exit(1)

    with open(CONFIG_PATH, "rb") as fp:
        cfg = GlobalConfigModel.model_validate_json(fp.read())
    debug = "--debug" in sys.argv or cfg.debug

    logger = Logger(level=LogLevel.DEBUG if debug else LogLevel.INFO)
    logger.debug("Config: " + cfg.model_dump_json(indent=4))
    os.makedirs("data", exist_ok=True)

    plugins = [resolve_plugin_path(p) for p in cfg.plugins]

    init_global_settings()
    get_checker_global_settings()

    bot = (
        Bot(
            "MiraiChan",
            logger=logger,
        )
        .add_io(
            ForwardWebSocketIO(
                url=cfg.forwwsio.url,
                access_token=cfg.forwwsio.access_token.get_secret_value(),
            )
        )
        .add_adapter(patch_all(Adapter()))
    )
    bot.load_plugins(plugins, load_depth=cfg.load_depth)

    bot.run(debug=debug, strict_log=debug)


if __name__ == "__main__":
    main()
