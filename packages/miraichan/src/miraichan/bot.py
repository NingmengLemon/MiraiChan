import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import json5
from lemony_checkers import init_checker_factory
from lemony_images import init_default_font_cache
from lemony_llm_provider.prompts.catgirl_assistant import EASTER_EGG_PROMPT
from lemony_settings import init_settings_manager
from lemony_storage_helper.database import set_relative_path_base
from melobot import Bot, add_import_fallback
from melobot.log import Logger, LogLevel
from melobot.log.reflect import set_global_logger
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO
from typer import Option, Typer

from .config import DEFAULT_CONFIG_PATH, GlobalConfigModel
from .loader import resolve_plugin_path
from .utils import ALTERNATIVE_LOGOS, custom_melobot_logo, get_project_root
from .validation_patches.ob11 import patch_all

if sys.platform == "win32":
    add_import_fallback("_sqlite3")
else:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logger = Logger()
miraichan_cli_app = Typer(name="miraichan", help="Miraichan CLI commands.")
custom_melobot_logo(ALTERNATIVE_LOGOS["no_logo"])


def init_modules(cfg: GlobalConfigModel):
    init_default_font_cache(cfg.default_font_path)
    init_settings_manager(
        preference=cfg.settings_format,
        config_root=cfg.config_root,
    )
    init_checker_factory()
    set_relative_path_base(get_project_root() / "data")


@miraichan_cli_app.command("launch", help="Launch Miraichan.")
def _(
    *,
    debug: bool = Option(
        False, "--debug", help="Whether to launch Miraichan in debug mode."
    ),
    no_easter_egg: bool = Option(
        False, "--no-easter-egg", help="Whether to disable the Easter egg."
    ),
    nyan: bool = Option(False, "--nyan", help="Whether to nyannnn~"),
    config_path: Path | None = Option(
        None, "--config-path", "-c", help="Path to the configuration file."
    ),
):
    _main(
        debug=debug,
        no_easter_egg=no_easter_egg,
        nyan=nyan,
        config_path=config_path,
    )


def main(
    debug: bool = False,
    no_easter_egg: bool = False,
    nyan: bool = False,
    config_path: Path | None = None,
):
    # 提供一个直接调用的入口, 以便在不使用命令行参数的情况下启动 Miraichan
    _main(
        debug=debug,
        no_easter_egg=no_easter_egg,
        nyan=nyan,
        config_path=config_path,
    )


def _main(
    debug: bool,
    no_easter_egg: bool,
    nyan: bool,
    config_path: Path | None,
):
    # print easter egg prompt if it's April 1st
    # and the user hasn't disabled it via command line argument
    if (not no_easter_egg and (d := datetime.now()).month == 4 and d.day == 1) or nyan:
        print(EASTER_EGG_PROMPT)

    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    set_global_logger(logger)

    logger.info("少女祈祷中... plz wait...")
    os.chdir(get_project_root())

    if not config_path.is_file():
        logger.error("配置文件 config.json 不存在, 无法启动 Miraichan.")
        logger.error("预期的位置: %s", config_path.resolve())
        sys.exit(1)

    with open(config_path, "rb") as fp:
        cfg = GlobalConfigModel.model_validate(json5.load(fp))
    debug = debug or cfg.debug
    logger.set_level(LogLevel.DEBUG if debug else LogLevel.INFO)

    logger.debug("Config: " + cfg.model_dump_json(indent=4))
    os.makedirs("data", exist_ok=True)

    init_modules(cfg)

    plugins = [resolve_plugin_path(p) for p in cfg.plugins]

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
    miraichan_cli_app()
