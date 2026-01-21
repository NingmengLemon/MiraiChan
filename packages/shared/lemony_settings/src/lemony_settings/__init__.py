"""
Lemony Settings - 配置管理库

一个基于 Pydantic 的配置管理库, 支持多种配置文件格式 (TOML, YAML, JSON),
以及自动重载和事件回调等功能.

快速开始:
    >>> from lemony_settings import (
    ...     BaseSettings,
    ...     init_global_settings,
    ...     require,
    ...     on_settings_event,
    ...     SettingsEventType,
    ... )
    >>>
    >>> # 定义你的配置模型
    >>> class MyPluginSettings(BaseSettings):
    ...     enabled: bool = True
    ...     message: str = "Hello, World!"
    ...
    >>> # 初始化全局设置 (程序启动时调用一次)
    >>> init_global_settings(preference="toml", config_path="configs")
    >>>
    >>> # 获取配置实例
    >>> settings = require(MyPluginSettings, "my_plugin")
    >>>
    >>> # 注册事件回调
    >>> @on_settings_event(SettingsEventType.RELOADED, identifier="my_plugin")
    ... def on_reload(event):
    ...     print(f"Config reloaded: {event.identifier}")
"""

from .core import (
    BaseSettings,
    GlobalSettings,
    LemonySettings,
    PersistentGlobalSettings,
    get_global_settings,
    init_global_settings,
    require,
    resolve_config_path,
)
from .events import (
    AsyncEventCallback,
    EventCallback,
    SettingsChangeEvent,
    SettingsErrorEvent,
    SettingsEvent,
    SettingsEventEmitter,
    SettingsEventType,
    SyncEventCallback,
    get_event_emitter,
    on_settings_event,
)
from .readwriter import (
    ConfigReadWriterABC,
    JsonReadWriter,
    TomlReadWriter,
    YamlReadWriter,
    get_read_writer,
    register_read_writer,
)
from .watcher import (
    ConfigFileWatcher,
    get_file_watcher,
    start_watcher,
    stop_watcher,
)

__all__ = [
    # core
    "BaseSettings",
    "LemonySettings",
    "GlobalSettings",
    "PersistentGlobalSettings",
    "init_global_settings",
    "get_global_settings",
    "require",
    "resolve_config_path",
    # events
    "SettingsEventType",
    "SettingsEvent",
    "SettingsChangeEvent",
    "SettingsErrorEvent",
    "SettingsEventEmitter",
    "EventCallback",
    "SyncEventCallback",
    "AsyncEventCallback",
    "get_event_emitter",
    "on_settings_event",
    # readwriter
    "ConfigReadWriterABC",
    "TomlReadWriter",
    "YamlReadWriter",
    "JsonReadWriter",
    "get_read_writer",
    "register_read_writer",
    # watcher
    "ConfigFileWatcher",
    "get_file_watcher",
    "start_watcher",
    "stop_watcher",
]
