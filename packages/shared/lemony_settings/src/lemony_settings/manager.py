import warnings
from os import PathLike
from pathlib import Path
from typing import Literal

from .core import GlobalSettings, LemonySettings
from .models import BaseSettings, PersistentGlobalSettings
from .readwriter import get_readwriter
from .utils import ensure_config_path, resolve_config_path


# not intended to be init by users
# not forced singleton, with a getter below, but should be used as if it's a singleton
class SettingsManager:
    def __init__(
        self,
        *,
        preference: Literal["json", "yaml"] | str,
        config_root: str | PathLike,
    ) -> None:
        # 规划的文件目录结构:
        # configs/  # 可以指定别的配置根目录
        #   global.json
        #   plugin_a/ # identifier
        #     a.toml  # namespace.toml
        #     b.toml
        #   plugin_b/
        #     c.toml
        #   module_x/
        #     x.toml
        # ...
        # 或许不是 toml
        # 因为 toml 不支持 None/null/nil, 又没有什么哨兵值可以用
        # 唉唉特立独行这一块
        self._config_root = Path(config_root)
        self._settings_table: dict[tuple[str, str], LemonySettings] = {}
        self._global_settings: GlobalSettings | None = None
        self._preference = preference
        self._readwriter = get_readwriter(preference)

        self._post_init()

    def _post_init(self):
        # 只是为了让 __init__() 看起来更清爽一点, 以及给未来可能的多实例化做准备.
        if self._global_settings is not None:
            raise RuntimeError("SettingsManager has already been initialized.")
        self._config_root.mkdir(parents=True, exist_ok=True)
        config_path_resolved = Path(self._config_root).resolve()
        global_config_file = resolve_config_path(
            config_path_resolved,
            self._preference,
            id_ns=None,
        )
        readwriter = get_readwriter(self._preference)
        if global_config_file.exists():
            persistent_global_settings = readwriter.read(
                global_config_file,
                PersistentGlobalSettings,
            )
        else:
            persistent_global_settings = PersistentGlobalSettings()
            ensure_config_path(global_config_file)
            readwriter.write(global_config_file, persistent_global_settings)

        self._global_settings = GlobalSettings(
            preference=self._preference,
            config_path=config_path_resolved,
            persistent=persistent_global_settings,
        )

    @property
    def global_settings(self) -> GlobalSettings:
        if (global_settings := self._global_settings) is not None:
            return global_settings
        raise RuntimeError("Global settings have not been initialized.")

    def require[T: BaseSettings](
        self,
        *,
        identifier: str,
        namespace: str,
        model: type[T],
        auto_load: bool = True,
    ) -> LemonySettings[T]:
        key = (identifier, namespace)
        if key in self._settings_table:
            existing_settings = self._settings_table[key]
            if existing_settings.model != model:
                raise ValueError(
                    f"Settings with '{identifier=}' and '{namespace=}' already exists with a different model."
                )
            return existing_settings
        new_settings = LemonySettings(
            identifier=identifier,
            namespace=namespace,
            model=model,
            manager=self,
        )
        if auto_load:
            new_settings.load()
        self._settings_table[key] = new_settings
        return new_settings


_manager_instance: SettingsManager | None = None


def init_settings_manager(
    *,
    preference: Literal["json", "yaml"] | str,
    config_root: str | PathLike,
) -> SettingsManager:
    """
    初始化全局的 SettingsManager 实例.
    """
    global _manager_instance
    if _manager_instance is not None:
        warnings.warn(
            "SettingsManager has already been initialized. Returning the existing instance."
        )
        return _manager_instance

    _manager_instance = SettingsManager(
        preference=preference,
        config_root=config_root,
    )
    return _manager_instance


def get_settings_manager() -> SettingsManager:
    """
    获取全局的 SettingsManager 实例。如果尚未初始化，会抛出异常。
    """
    if _manager_instance is None:
        raise RuntimeError(
            "SettingsManager has not been initialized. Call init_settings_manager() first."
        )
    return _manager_instance


def _reset_for_testing() -> None:
    """将全局 SettingsManager 实例重置为 None.

    **仅供测试使用.** 在每个需要重新初始化的测试用例前调用.
    生产代码中禁止调用此函数.

    Example::

        def setup_function():
            lemony_settings.manager._reset_for_testing()
    """
    global _manager_instance
    _manager_instance = None
