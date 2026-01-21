import re
import textwrap
from enum import Enum, auto
from pathlib import Path
from typing import Any, Literal

from melobot.log import get_logger
from pydantic import BaseModel, Field, ValidationError

from .readwriter import get_read_writer

logger = get_logger()

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][0-9A-Za-z_]{0,31}$")


class BaseSettings(BaseModel):
    """
    所有设置模型的基类.

    每个字段都需要有一个默认值, 以确保设置模型可以被正确初始化.
    支持 auto_save: 当字段被修改时, 如果启用了 auto_save, 会自动保存到文件.
    """

    # 内部引用, 用于 auto_save 功能
    _settings_ref: "LemonySettings | None" = None

    model_config = {"validate_assignment": True}

    def __setattr__(self, name: str, value: Any) -> None:
        # 检查是否是模型字段 (排除私有属性)
        is_model_field = (
            not name.startswith("_") and name in self.__class__.model_fields
        )

        old_value: Any = None
        if is_model_field:
            old_value = getattr(self, name, None) if hasattr(self, name) else None

        # 调用父类的 __setattr__ 来设置值
        super().__setattr__(name, value)

        # 如果是模型字段且值发生了变化, 触发 auto_save
        if is_model_field:
            try:
                settings_ref: "LemonySettings | None" = object.__getattribute__(
                    self, "_settings_ref"
                )
            except AttributeError:
                # _settings_ref 尚未设置 (模型刚初始化时)
                settings_ref = None
            if settings_ref is not None:
                new_value = getattr(self, name)
                if old_value != new_value:
                    settings_ref._on_value_changed(name, old_value, new_value)


_SETTINGS_TABLE: dict[tuple[str, str], "LemonySettings"] = {}
_global_settings: "GlobalSettings | None" = None


class _Sentinel(Enum):
    NOT_LOADED = auto()


# 这个类不是给用户直接初始化的, 而是通过 require() 函数来获取实例.
class LemonySettings[SettingModelT: BaseSettings]:
    def __init__(
        self,
        identifier: str,
        namespace: str,
        model: type[SettingModelT],
    ) -> None:
        self._identifier = self._check_pattern_match(IDENTIFIER_PATTERN, identifier)
        self._namespace = self._check_pattern_match(IDENTIFIER_PATTERN, namespace)
        if (identifier, namespace) in _SETTINGS_TABLE:
            raise ValueError(
                f"settings with identifier '{identifier}' and namespace '{namespace}' already exists."
            )

        self._value: SettingModelT | Literal[_Sentinel.NOT_LOADED] = (
            _Sentinel.NOT_LOADED
        )
        self._model = model
        self._is_saving = False  # 防止保存时触发重载
        _SETTINGS_TABLE[(identifier, namespace)] = self
        # value 由插件自己进行懒加载
        # 在加载前就尝试读取 value 需要报错

    def _check_pattern_match(self, pattern: str | re.Pattern, value: str) -> str:
        if re.fullmatch(pattern, value) is None:
            raise ValueError(f"Value '{value}' does not match the pattern '{pattern}'")
        return value

    def _check_init_value(self, value: SettingModelT | None) -> SettingModelT:
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
        if self._value is _Sentinel.NOT_LOADED:
            raise RuntimeError(
                f"Settings '{self._identifier}:{self._namespace}' has not been loaded yet."
            )
        return self._value

    def _on_value_changed(
        self, field_name: str, old_value: Any, new_value: Any
    ) -> None:
        """
        当配置值被修改时调用.
        用于触发 auto_save 和事件通知.
        """
        from .events import (
            SettingsChangeEvent,
            SettingsEventType,
            get_event_emitter,
        )

        # 触发 AFTER_CHANGE 事件
        emitter = get_event_emitter()
        event = SettingsChangeEvent(
            event_type=SettingsEventType.AFTER_CHANGE,
            identifier=self._identifier,
            namespace=self._namespace,
            old_value=None,  # 这里只传递字段级别的变化信息
            new_value=None,
            changed_fields=[field_name],
        )
        emitter.emit_sync(event)

        # 检查是否启用 auto_save
        try:
            global_settings = get_global_settings()
            if global_settings.filed.auto_save and not self._is_saving:
                self.save()
                logger.debug(
                    f"Auto-saved settings '{self._identifier}:{self._namespace}' "
                    f"after field '{field_name}' changed."
                )
        except RuntimeError:
            # GlobalSettings 尚未初始化, 跳过 auto_save
            pass

    # 规划的的文件目录结构:
    # configs/  # 或许可以接收命令行参数来指定别的目录
    #   global.toml
    #   plugin_a/ # identifier
    #     a.toml  # namespace.toml
    #     b.toml
    #   plugin_b/
    #     c.toml
    #   module_x/
    #     x.toml

    def _load_from_file(
        self, path: Path, format: Literal["toml", "yaml", "json"]
    ) -> SettingModelT:
        """
        从指定路径加载配置文件并返回对应的设置模型实例.
        """
        readwriter = get_read_writer(format)
        data = readwriter.read(path, self._model)
        try:
            model_instance = self._model.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"Failed to validate config data: {e}") from e
        return model_instance

    def save(self) -> None:
        """
        将当前设置值保存到配置文件中.
        """
        from .events import (
            SettingsErrorEvent,
            SettingsEvent,
            SettingsEventType,
            get_event_emitter,
        )
        from .watcher import get_file_watcher

        if self._value is _Sentinel.NOT_LOADED:
            raise RuntimeError(
                f"Settings '{self._identifier}:{self._namespace}' has not been loaded yet."
            )

        global_settings = get_global_settings()
        config_file = resolve_config_path(
            global_settings.config_path,
            global_settings.preference,
            id_ns=(self._identifier, self._namespace),
        )

        # 标记正在保存, 防止触发重载
        self._is_saving = True
        watcher = get_file_watcher()
        if watcher is not None:
            watcher.mark_saving(config_file)

        try:
            readwriter = get_read_writer(global_settings.preference)
            readwriter.write(config_file, self._value)

            # 触发 SAVED 事件
            emitter = get_event_emitter()
            event = SettingsEvent(
                event_type=SettingsEventType.SAVED,
                identifier=self._identifier,
                namespace=self._namespace,
                config_path=config_file,
            )
            emitter.emit_sync(event)

        except Exception as e:
            # 触发 SAVE_ERROR 事件
            emitter = get_event_emitter()
            event = SettingsErrorEvent(
                event_type=SettingsEventType.SAVE_ERROR,
                identifier=self._identifier,
                namespace=self._namespace,
                config_path=config_file,
                error=e,
                error_message=str(e),
            )
            emitter.emit_sync(event)
            raise
        finally:
            self._is_saving = False
            if watcher is not None:
                watcher.unmark_saving(config_file)

    def load(self) -> None:
        """
        从配置文件中加载设置值.
        如果配置文件不存在, 则使用默认值初始化并保存到文件中.
        """
        global_settings = get_global_settings()
        config_file = resolve_config_path(
            global_settings.config_path,
            global_settings.preference,
            id_ns=(self._identifier, self._namespace),
        )
        if config_file.exists():
            self._value = self._load_from_file(config_file, global_settings.preference)
        else:
            self._value = self._check_init_value(None)
            self.save()
            logger.info(
                f"config file {self._identifier}:{self._namespace} does not exist. "
                f"Initialized with default values and saved as {config_file!r}.",
            )

        # 设置 settings 引用, 以便 auto_save 功能工作
        if self._value is not _Sentinel.NOT_LOADED:
            object.__setattr__(self._value, "_settings_ref", self)


def resolve_config_path(
    config_path: str | Path,
    preference: Literal["toml", "yaml", "json"],
    id_ns: tuple[str, str] | None = None,
) -> Path:
    """
    获取当前设置对应的配置文件路径.
    """
    config_root = Path(config_path).resolve()
    config_root.mkdir(parents=True, exist_ok=True)

    if id_ns is None:
        return config_root / f"global.{preference}"
    identifier, namespace = id_ns
    file = config_root / identifier / f"{namespace}.{preference}"
    file.parent.mkdir(parents=True, exist_ok=True)
    return file


class GlobalSettings(BaseModel):
    # 分为可持久化的设置和非持久化的设置.
    # 可持久化的设置会被保存到配置文件中.
    preference: Literal["toml", "yaml", "json"] = Field(
        default="toml",
        description=textwrap.dedent(
            """
            配置文件的首选格式.
            支持 'toml', 'yaml', 'json'.
            """,
        ).strip(),
        frozen=True,
    )
    config_path: str | Path = Field(
        default="configs",
        description=textwrap.dedent(
            """
            配置文件的存储目录.
            """,
        ).strip(),
        frozen=True,
    )
    # 上述两个字段是非持久化的, 将在初始化时传入.
    # 比如, 开发者可以把它做成命令行参数传入.

    # 下面的字段是可持久化字段的数据模型.
    filed: "FiledGlobalSettings" = Field(
        default_factory=lambda: FiledGlobalSettings(),
        description=textwrap.dedent(
            """
            全局设置的文件相关设置.
            """,
        ).strip(),
        frozen=False,  # frozen 不作用于嵌套模型的内容
    )

    def save(self) -> None:
        """
        将全局设置的可持久化字段保存到配置文件中.
        """
        config_file = resolve_config_path(
            self.config_path,
            self.preference,
            id_ns=None,
        )
        readwriter = get_read_writer(self.preference)
        readwriter.write(config_file, self.filed)


class FiledGlobalSettings(BaseModel):
    # 这些设定会保存到 configs/global.{preference} 文件中.
    auto_save: bool = Field(
        default=True,
        description=textwrap.dedent(
            """
            是否启用自动保存功能.
            启用后, 当设置值被修改时, 会自动保存到配置文件中.
            """,
        ).strip(),
    )
    auto_reload: bool = Field(
        default=False,
        description=textwrap.dedent(
            """
            是否启用自动重载功能.
            启用后, 当设置值在配置文件中被修改时, 会自动重新加载.
            """,
        ).strip(),
    )


def require[T: BaseSettings](
    model: type[T], identifier: str, namespace: str = "default"
) -> T:
    """
    获取一个 LemonySettings 实例. 如果不存在则创建一个新的实例并返回其值.
    """
    key = (identifier, namespace)
    if key not in _SETTINGS_TABLE:
        settings = LemonySettings(
            identifier=identifier,
            namespace=namespace,
            model=model,
        )
        _SETTINGS_TABLE[key] = settings
    return _SETTINGS_TABLE[key].value


def init_global_settings(
    preference: Literal["toml", "yaml", "json"] = "toml",
    config_path: str | Path = "configs",
) -> GlobalSettings:
    """
    初始化全局设置.

    这个函数应该在程序启动时调用, 且只能调用一次.
    如果启用了 auto_reload, 需要在之后调用 start_watcher() 来启动文件监控.
    """
    from .watcher import init_file_watcher

    global _global_settings
    if _global_settings is not None:
        raise RuntimeError("GlobalSettings has already been initialized.")

    config_path_resolved = Path(config_path).resolve()
    global_config_file = resolve_config_path(
        config_path_resolved,
        preference,
        id_ns=None,
    )
    readwriter = get_read_writer(preference)
    if global_config_file.exists():
        filed_global_settings = readwriter.read(
            global_config_file,
            FiledGlobalSettings,
        )
    else:
        filed_global_settings = FiledGlobalSettings()
        readwriter.write(global_config_file, filed_global_settings)

    global_settings = GlobalSettings(
        preference=preference,
        config_path=config_path_resolved,
        filed=filed_global_settings,
    )
    _global_settings = global_settings

    # 初始化文件监控器 (但不启动, 需要手动调用 start_watcher)
    init_file_watcher(config_path_resolved, preference)

    return global_settings


def get_global_settings() -> GlobalSettings:
    """
    获取全局设置实例.
    """
    if _global_settings is None:
        raise RuntimeError("GlobalSettings has not been initialized yet.")
    return _global_settings
