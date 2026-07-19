import asyncio
import os
import sys
from logging import setLoggerClass
from pathlib import Path

import json5
import melobot
from lemony_checkers import init_checker_factory
from lemony_images import init_default_font_cache
from lemony_settings import init_settings_manager
from lemony_storage_helper.database.sqlite import set_relative_path_base
from melobot import Bot, add_import_fallback
from melobot.log import Logger, LogLevel
from melobot.log.reflect import set_global_logger
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO, ReverseWebSocketIO
from packaging.version import Version
from typer import Option, Typer

from .config import (
    DEFAULT_CONFIG_PATH,
    ForwardWebsocketIOConfigModel,
    GlobalConfigModel,
    ReverseWebsocketIOConfigModel,
)
from .loader import resolve_plugin_path
from .utils import ALTERNATIVE_LOGOS, customize_melobot_logo, get_project_root

if sys.platform == "win32":
    add_import_fallback("_sqlite3")
else:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

MELOBOT_VERSION = Version(melobot.__version__)


logger = Logger()
miraichan_cli_app = Typer(name="miraichan", help="Miraichan CLI commands.")
customize_melobot_logo(ALTERNATIVE_LOGOS["no_logo"])


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
    config_path: Path | None = Option(
        None, "--config-path", "-c", help="Path to the configuration file."
    ),
):
    _main(
        debug=debug,
        config_path=config_path,
    )


def main(
    debug: bool = False,
    config_path: Path | None = None,
):
    # 提供一个直接调用的入口, 以便在不使用命令行参数的情况下启动 Miraichan
    _main(
        debug=debug,
        config_path=config_path,
    )


def _io_from_config_model(
    cfg: ForwardWebsocketIOConfigModel | ReverseWebsocketIOConfigModel,
):
    if isinstance(cfg, ForwardWebsocketIOConfigModel):
        return ForwardWebSocketIO(
            url=cfg.url,
            access_token=cfg.access_token.get_secret_value(),
            cd_time=cfg.cd_time,
        )
    elif isinstance(cfg, ReverseWebsocketIOConfigModel):
        return ReverseWebSocketIO(
            host=cfg.host,
            port=cfg.port,
            access_token=cfg.access_token.get_secret_value(),
            cd_time=cfg.cd_time,
        )
    raise ValueError(f"Invalid websocket config type: {type(cfg)}")


def _setup_logging():
    # logging configs
    if Version("3.2.0") <= MELOBOT_VERSION < Version("3.5.0"):
        from .melobot_patches.logging import patch_melobot_thread_logging

        # 目前 (3.4.0, 相关函数简单追溯到了 3.2.0, 未测试) 的 melobot 的日志器在多线程环境有问题
        # 在 3.5.0 修了
        patch_melobot_thread_logging()

    set_global_logger(logger)
    # 让使用 logging 记日志的库也使用全局日志记录器
    setLoggerClass(Logger)


def _main(
    debug: bool,
    config_path: Path | None,
):
    from .validation_patches.ob11 import patch_all

    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    _setup_logging()

    logger.info("少女祈祷中... plz wait...")
    os.chdir(get_project_root())

    if not config_path.is_file():
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as fp:
                fp.write(
                    GlobalConfigModel().model_dump_json(
                        indent=4, exclude_none=True, by_alias=True
                    )
                )
            logger.error("配置文件 config.json 不存在, 已创建默认配置文件")
            logger.error("请根据需要修改配置文件后重新启动 MiraiChan.")
        except Exception as e:
            logger.error("无法创建配置文件 config.json: %s", e)
            logger.error("请检查权限或手动创建配置文件.")
        logger.error("预期的配置文件位置: %s", config_path.resolve())
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
        .add_io(_io_from_config_model(cfg.websocket))
        .add_adapter(patch_all(Adapter()))
    )
    bot.load_plugins(plugins, load_depth=cfg.load_depth)
    bot.run(debug=debug, strict_log=debug)


if __name__ == "__main__":
    miraichan_cli_app()
