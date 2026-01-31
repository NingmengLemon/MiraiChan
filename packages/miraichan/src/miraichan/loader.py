import importlib
import importlib.util
from os import PathLike
from pathlib import Path
from types import ModuleType

from melobot.exceptions import PluginLoadError
from melobot.log import get_logger
from melobot.plugin.base import PluginPlanner

logger = get_logger()
type Loadable = ModuleType | str | PathLike[str] | PluginPlanner


def resolve_plugin_path(plugin_name: str) -> Loadable:
    # 0. 直接作为路径存在 (相对或绝对)
    if (p := Path(plugin_name)).is_dir():
        logger.info(f"Resolved plugin path for {plugin_name!r} as direct path.")
        return p.resolve()
    logger.debug(f"Plugin name {plugin_name!r} is not a direct path.")

    # 1. 作为本地插件存在 (plugins/ 下)
    local_plugin_path = Path.cwd() / "plugins" / plugin_name
    if local_plugin_path.is_dir():
        logger.info(f"Resolved plugin path for {plugin_name!r} as local plugin path.")
        return local_plugin_path.resolve()
    logger.debug(
        f"Plugin name {plugin_name!r} ({local_plugin_path}) is not a local plugin path."
    )

    # 2. 作为已安装的包存在 (当前(虚拟)环境中)
    try:
        # 直接导入作为 moduletype
        spec = importlib.util.find_spec(plugin_name)
        logger.debug(f"find_spec result for {plugin_name!r}: {spec!r}")
        if spec is not None and spec.origin is not None:
            module = importlib.import_module(plugin_name)
            logger.info(
                f"Resolved plugin path for {plugin_name!r} as installed package: {module!r}."
            )
            return module
    except ModuleNotFoundError:
        pass  # 后面还有流程, 你先别急
    logger.debug(f"Plugin name {plugin_name!r} is not an installed package.")

    # 3. url 形式的远程插件
    pass  # TODO: 实现远程插件加载

    # -1. 作为项目自带的插件存在
    packages_dir = Path(__file__).parent.parent.parent.parent.resolve()
    candidate_path = packages_dir / "plugins" / plugin_name
    if candidate_path.is_dir():
        logger.info(
            f"Resolved plugin path for {plugin_name!r} as built-in plugin path."
        )
        return candidate_path
    logger.debug(f"Plugin name {plugin_name!r} is not a built-in plugin path.")
    raise PluginLoadError(f"Cannot resolve plugin path for {plugin_name!r}")
