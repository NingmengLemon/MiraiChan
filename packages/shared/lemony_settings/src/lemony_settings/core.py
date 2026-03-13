from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from filelock import FileLock
from pydantic import ValidationError

from .models import BaseSettings, GlobalSettings
from .readwriter import get_readwriter
from .utils import check_identifier, ensure_config_path, resolve_config_path

if TYPE_CHECKING:
    from .manager import SettingsManager

logger = getLogger(__name__)


# TODO: 完全异步化
# 这个类不是给用户直接初始化的, 而是通过 require() 函数来获取实例.
class LemonySettings[SettingModelT: BaseSettings]:
    def __init__(
        self,
        identifier: str,
        namespace: str,
        model: type[SettingModelT],
        manager: "SettingsManager",
    ) -> None:
        self._identifier = check_identifier(identifier)
        self._namespace = check_identifier(namespace)
        self._model = model
        self._manager = manager
        self._value: SettingModelT | None = None  # None 表示尚未加载

        # value 由插件自己进行懒加载
        # 在加载前就尝试读取 value 需要报错
        # 向 manager 注册的工作由 manager 的 require() 方法来完成

    def _resolve_value(self, value: SettingModelT | None) -> SettingModelT:
        """确保返回一个有效的设置值. 如果 value 为 None, 则使用 model 的默认值初始化."""
        # 不允许直接把 BaseSettings 作为 model 类型.
        if self._model is BaseSettings:
            raise TypeError(
                "model cannot be BaseSettings directly, inherit a subclass instead"
            )
        if not issubclass(self._model, BaseSettings):
            raise TypeError("model must be a subclass of BaseSettings")
        # 如果 value 是 None, 则使用 model 的默认值初始化.
        # 这就是为什么 BaseSettings 的字段必须有默认值.
        if value is None:
            try:
                model_instance = self._model()
            except ValidationError as e:
                missing_default_fields = [
                    err["loc"][0] for err in e.errors() if err["type"] == "missing"
                ]

                if missing_default_fields:
                    raise ValueError(
                        f"Failed to initialize value.\n"
                        f"Missing default values for fields: {missing_default_fields!r}"
                    ) from e
                raise ValueError(f"Failed to initialize value: {e}") from e
            except Exception as e:
                raise ValueError(f"Failed to initialize value: {e}") from e
            return model_instance
        return value

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def id(self) -> str:
        return self._identifier

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def model(self) -> type[SettingModelT]:
        return self._model

    @property
    def value(self) -> SettingModelT:
        if self._value is None:
            raise RuntimeError(
                f"Settings '{self._identifier}:{self._namespace}' has not been loaded yet."
            )
        return self._value

    def _load_from_file(
        self, path: Path, format: Literal["yaml", "json"] | str
    ) -> SettingModelT:
        """
        从指定路径加载配置文件并返回对应的设置模型实例.
        """
        readwriter = get_readwriter(format)
        try:
            model_instance = readwriter.read(path, self._model)
        except ValidationError as e:
            raise ValueError(f"Failed to validate config data: {e}") from e
        return model_instance

    def save(self) -> None:
        """
        将当前设置值保存到配置文件中.
        """
        if self._value is None:
            raise RuntimeError(
                f"Settings '{self._identifier}:{self._namespace}' has not been loaded yet."
            )

        global_settings = self._manager.global_settings
        config_file = resolve_config_path(
            global_settings.config_path,
            global_settings.preference,
            id_ns=(self._identifier, self._namespace),
        )

        lock_file = config_file.with_suffix(config_file.suffix + ".lock")
        lock = FileLock(lock_file, timeout=10)
        try:
            with lock:
                ensure_config_path(config_file)
                readwriter = get_readwriter(global_settings.preference)
                readwriter.write(config_file, self._value)
        except Exception as e:
            logger.error(
                f"Failed to save settings '{self._identifier}:{self._namespace}': {e}"
            )
            raise

    def load(self) -> None:
        """
        从配置文件中加载设置值.
        如果配置文件不存在, 则使用默认值初始化并保存到文件中.
        """
        global_settings = self._manager.global_settings
        config_file = resolve_config_path(
            global_settings.config_path,
            global_settings.preference,
            id_ns=(self._identifier, self._namespace),
        )
        lock_file = config_file.with_suffix(config_file.suffix + ".lock")
        lock = FileLock(lock_file, timeout=10)
        with lock:
            if config_file.exists():
                self._value = self._load_from_file(
                    config_file, global_settings.preference
                )
            else:
                self._value = self._resolve_value(None)
                # 在锁内保存, 避免竞态
                ensure_config_path(config_file)
                readwriter = get_readwriter(global_settings.preference)
                readwriter.write(config_file, self._value)
                logger.info(
                    f"config file {self._identifier}:{self._namespace} does not exist. "
                    f"Initialized with default values and saved as {config_file!r}.",
                )


# proxy for manager method
def require[T: BaseSettings](
    *,
    identifier: str,
    model: type[T],
    namespace: str = "default",
    auto_load: bool = True,
) -> LemonySettings[T]:
    """
    获取一个 LemonySettings 实例. 如果不存在则创建一个新的实例并返回其值.
    """
    # lazy import to avoid circular import
    from .manager import get_settings_manager

    manager = get_settings_manager()
    return manager.require(
        identifier=identifier,
        namespace=namespace,
        model=model,
        auto_load=auto_load,
    )


def get_global_settings() -> GlobalSettings:
    """
    获取全局设置实例. shortcut for get_settings_manager().global_settings
    """
    from .manager import get_settings_manager

    return get_settings_manager().global_settings
