"""
packages.shared.lemony_settings.src.lemony_settings.manager 的 Docstring

基于文件系统的配置管理器
configs/
    plugin1/
        setting1.toml
        setting2.toml
    plugin2/
        setting1.toml
    global.toml
"""

import textwrap
from pathlib import Path
from typing import Literal, TypedDict

from melobot.utils import singleton
from pydantic import BaseModel, Field


@singleton
class ConfigManager:
    def __init__(
        self,
        config_path: str | Path,
        preference: Literal["toml", "yaml", "json"] = "toml",
    ) -> None:
        self._config_path = Path(config_path).resolve()
        self._config_path.mkdir(parents=True, exist_ok=True)

        self._plugin_configs: dict[str, dict[str, Path]] = {
            # plugin_name: { setting_name: setting_path }
        }
        self._global_config: Path = self._config_path / f"global.{preference}"

        self.__post_init()

    def __post_init(self):
        for item in self._config_path.iterdir():
            if item.is_dir():
                plugin_name = item.name
                self._plugin_configs[plugin_name] = {}
                for setting_file in item.iterdir():
                    if setting_file.is_file():
                        setting_name = setting_file.stem
                        self._plugin_configs[plugin_name][setting_name] = setting_file
