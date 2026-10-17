import asyncio
import logging
import os
import sys
from pathlib import Path

import json5
from lemony_checkers import init_checker_factory
from lemony_images import init_default_font_cache
from lemony_settings import (
    ensure_credentials_file,
    init_settings_manager,
    set_credentials_path,
    warn_if_insecure,
)
from lemony_storage_helper.files import set_data_root
from melobot import Bot, add_import_fallback
from melobot.log import Logger, LogLevel
from melobot.log.reflect import set_global_logger
from melobot.protocols.onebot.v11 import Adapter, ForwardWebSocketIO, ReverseWebSocketIO
from typer import Option, Typer

from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_CREDENTIALS_PATH,
    ForwardWebsocketIOConfigModel,
    GlobalConfigModel,
    ReverseWebsocketIOConfigModel,
    apply_credential_overrides,
    plaintext_token_present,
)
from .loader import Loadable, resolve_plugin_path
from .logging_bridge import install_logging_bridge
from .utils import ALTERNATIVE_LOGOS, customize_melobot_logo, get_project_root

if sys.platform == "win32":
    add_import_fallback("_sqlite3")
else:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

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
    # 数据库相对路径也以 data root 为根 (SqliteDatabaseHelper 会退回到它)
    set_data_root(get_project_root() / "data")


def _resolve_plugins(names: list[str]) -> list[tuple[str, Loadable]]:
    """解析插件名; 单个插件解析失败只记录并跳过, 不拖垮其他插件"""
    resolved: list[tuple[str, Loadable]] = []
    for name in names:
        try:
            resolved.append((name, resolve_plugin_path(name)))
        except Exception:
            logger.exception(f"插件 {name!r} 解析失败, 已跳过")
    return resolved


def _load_plugins(
    bot: Bot, plugins: list[tuple[str, Loadable]], *, load_depth: int
) -> None:
    """逐个加载插件.

    melobot 的 Bot.load_plugins 是裸循环: 任何一个插件抛异常都会中断后续所有插件的加载,
    于是一个坏插件就能让整个 bot 起不来。这里逐个隔离, 失败的记录在案并汇总。
    """
    failed: list[str] = []
    for name, plugin in plugins:
        try:
            # load_depth 在 melobot 里是仅限位置参数; 按关键字传会落进 **init_args
            bot.load_plugin(plugin, load_depth)
        except Exception:
            failed.append(name)
            logger.exception(f"插件 {name!r} 加载失败, 已跳过")
    if failed:
        logger.error(
            f"{len(failed)}/{len(plugins)} 个插件加载失败: {', '.join(failed)}; "
            "其余插件已正常加载"
        )


@miraichan_cli_app.command("launch", help="Launch Miraichan.")
def _(
    *,
    debug: bool = Option(
        False, "--debug", help="Whether to launch Miraichan in debug mode."
    ),
    config_path: Path | None = Option(
        None, "--config-path", "-c", help="Path to the configuration file."
    ),
    credentials_path: Path | None = Option(
        None, "--credentials-path", help="Path to the credentials file."
    ),
):
    _main(
        debug=debug,
        config_path=config_path,
        credentials_path=credentials_path,
    )


def main(
    debug: bool = False,
    config_path: Path | None = None,
    credentials_path: Path | None = None,
):
    # 提供一个直接调用的入口, 以便在不使用命令行参数的情况下启动 Miraichan
    _main(
        debug=debug,
        config_path=config_path,
        credentials_path=credentials_path,
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
    if isinstance(cfg, ReverseWebsocketIOConfigModel):
        return ReverseWebSocketIO(
            host=cfg.host,
            port=cfg.port,
            access_token=cfg.access_token.get_secret_value(),
            cd_time=cfg.cd_time,
        )
    raise ValueError(f"Invalid websocket config type: {type(cfg)}")


def _setup_logging(*, debug: bool, levels: dict[str, str]) -> None:
    set_global_logger(logger)
    logger.set_level(LogLevel.DEBUG if debug else LogLevel.INFO)
    # 标准 logging 的记录统一转给 melobot 日志器输出, 级别由 logging 层级控制
    install_logging_bridge(
        logger,
        root_level=logging.DEBUG if debug else logging.INFO,
        levels=levels,
    )


def _main(
    debug: bool,
    config_path: Path | None,
    credentials_path: Path | None = None,
):
    from .validation_patches.ob11 import patch_all

    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    set_credentials_path(credentials_path or DEFAULT_CREDENTIALS_PATH)
    set_global_logger(logger)

    logger.info("少女祈祷中... plz wait...")
    os.chdir(get_project_root())

    try:
        ensure_credentials_file(template={"websocket.access_token": ""})
    except OSError:
        logger.exception(
            "无法创建凭据文件, 本次启动只能依赖环境变量或配置里的明文 access_token"
        )
    warn_if_insecure()

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
        except OSError:
            logger.exception(
                "无法创建配置文件 config.json, 请检查权限或手动创建配置文件."
            )
        logger.error("预期的配置文件位置: %s", config_path.resolve())
        sys.exit(1)

    with open(config_path, "rb") as fp:
        raw_cfg = json5.load(fp)
    if plaintext_token_present(raw_cfg):
        logger.warning(
            "config.json 里还有明文的 websocket.access_token, "
            "建议挪到凭据文件或环境变量后删掉这一项"
        )
    cfg = GlobalConfigModel.model_validate(apply_credential_overrides(raw_cfg))
    debug = debug or cfg.debug
    _setup_logging(debug=debug, levels=cfg.log_levels)

    logger.debug("Config: " + cfg.model_dump_json(indent=4))
    os.makedirs(get_project_root() / "data", exist_ok=True)

    init_modules(cfg)

    plugins = _resolve_plugins(cfg.plugins)

    bot = (
        Bot(
            "MiraiChan",
            logger=logger,
        )
        .add_io(_io_from_config_model(cfg.websocket))
        .add_adapter(patch_all(Adapter()))
    )
    _load_plugins(bot, plugins, load_depth=cfg.load_depth)
    bot.run(debug=debug, strict_log=debug)


if __name__ == "__main__":
    miraichan_cli_app()
