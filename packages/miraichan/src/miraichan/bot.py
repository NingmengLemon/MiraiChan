import asyncio
import os
import sys
from datetime import datetime

import json5
from lemony_checkers import init_checker_factory
from lemony_llm_provider.prompts.catgirl_assistant import EASTER_EGG_PROMPT
from lemony_settings import init_settings_manager
from melobot import Bot, add_import_fallback
from melobot.log import Logger, LogLevel
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO

from .config import CONFIG_PATH, GlobalConfigModel
from .loader import resolve_plugin_path
from .utils import get_project_root
from .validation_patches.ob11 import patch_all

if sys.platform == "win32":
    add_import_fallback("_sqlite3")
else:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def main():
    os.chdir(get_project_root())
    if not CONFIG_PATH.exists():
        print("配置文件 config.json 不存在, 无法启动 Miraichan.")
        print("预期的位置: ", CONFIG_PATH.resolve())
        sys.exit(1)

    with open(CONFIG_PATH, "rb") as fp:
        cfg = GlobalConfigModel.model_validate(json5.load(fp))
    debug = "--debug" in sys.argv or cfg.debug

    logger = Logger(level=LogLevel.DEBUG if debug else LogLevel.INFO)
    logger.debug("Config: " + cfg.model_dump_json(indent=4))
    os.makedirs("data", exist_ok=True)

    plugins = [resolve_plugin_path(p) for p in cfg.plugins]

    init_settings_manager(
        preference=cfg.settings_format,
        config_root=cfg.config_root,
    )
    init_checker_factory()

    # print easter egg prompt if it's April 1st
    # and the user hasn't disabled it via command line argument
    if (
        ("--no-easter-egg" not in sys.argv)
        and (d := datetime.now()).month == 4
        and d.day == 1
    ) or "--nyan" in sys.argv:
        print(EASTER_EGG_PROMPT)

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
