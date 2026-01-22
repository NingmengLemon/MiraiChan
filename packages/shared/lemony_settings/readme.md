# Lemony Settings

一个基于 Pydantic 的配置管理库，专为 MiraiChan 设计。支持多种配置文件格式 (TOML, YAML, JSON)，以及自动重载和事件回调等功能。

## ✨ 特性

- 🔧 **类型安全** - 基于 Pydantic BaseModel，享受完整的类型提示和验证
- 📁 **多格式支持** - 支持 TOML、YAML、JSON 三种配置文件格式
- 🔄 **自动重载** - 监控配置文件变化，自动重新加载
- 📡 **事件系统** - 支持同步/异步的配置变更事件回调
- 🔌 **可扩展** - 可以注册自定义的配置读写器

## 📦 安装

```bash
# 使用 uv (推荐)
uv add lemony_settings

# 或使用 pip
pip install lemony_settings
```

## 🚀 快速开始

### 基本用法

```python
from lemony_settings import (
    BaseSettings,
    LemonySettings,
    init_global_settings,
    require,
)

# 1. 定义你的配置模型
class MyPluginSettings(BaseSettings):
    enabled: bool = True
    message: str = "Hello, World!"
    max_retries: int = 3

# 2. 初始化全局设置 (程序启动时调用一次)
init_global_settings(
    preference="toml",      # 配置文件格式
    config_path="configs",  # 配置文件目录
)

# 3. 创建并加载配置
settings = LemonySettings(
    identifier="my_plugin",   # 插件/模块标识符
    namespace="default",      # 命名空间
    model=MyPluginSettings,   # 配置模型类
)
settings.load()  # 加载配置 (如果文件不存在则创建默认配置)

# 4. 使用配置
print(settings.value.message)  # "Hello, World!"
settings.value.max_retries = 5  # 修改配置
settings.save()  # 手动保存到文件
```

### 配置文件结构

配置文件将按以下结构组织：

```
configs/
├── global.toml           # 全局设置
├── my_plugin/
│   └── default.toml      # my_plugin:default 的配置
├── another_plugin/
│   ├── settings.toml     # another_plugin:settings
│   └── advanced.toml     # another_plugin:advanced
```

## 📖 详细用法

### 定义配置模型

配置模型必须继承自 `BaseSettings`，所有字段都需要有默认值：

```python
from lemony_settings import BaseSettings
from typing import Optional

class DatabaseSettings(BaseSettings):
    host: str = "localhost"
    port: int = 5432
    username: str = "admin"
    password: Optional[str] = None  # 可选字段
    pool_size: int = 10

class CacheSettings(BaseSettings):
    enabled: bool = True
    ttl: int = 3600
    max_size: int = 1000
```

### 全局设置

全局设置控制整个配置系统的行为：

```python
from lemony_settings import init_global_settings, get_global_settings

# 初始化 (只能调用一次)
global_settings = init_global_settings(
    preference="toml",       # 支持 "toml", "yaml", "json"
    config_path="configs",   # 配置文件根目录
)

# 获取全局设置
gs = get_global_settings()

# 全局设置的可配置选项 (保存在 configs/global.toml)
gs.persistent.auto_reload = True  # 是否启用自动重载
gs.save()  # 保存全局设置
```

### 事件系统

监听配置变更事件：

```python
from lemony_settings import (
    on_settings_event,
    SettingsEventType,
    SettingsEvent,
    SettingsChangeEvent,
)

# 监听配置重载事件
@on_settings_event(SettingsEventType.RELOADED)
def on_any_reload(event: SettingsEvent):
    print(f"配置 {event.identifier}:{event.namespace} 已重载")

# 监听特定配置的事件
@on_settings_event(
    SettingsEventType.RELOADED, 
    identifier="my_plugin",
    namespace="default"
)
async def on_my_plugin_reload(event: SettingsChangeEvent):
    print(f"my_plugin 配置已重载，变更字段: {event.changed_fields}")

# 监听错误事件
@on_settings_event(SettingsEventType.LOAD_ERROR)
def on_error(event):
    print(f"配置加载失败: {event.error_message}")
```

#### 事件类型

| 事件类型 | 说明 |
|---------|------|
| `RELOADED` | 配置文件被重新加载 |
| `SAVED` | 配置文件被保存 |
| `LOAD_ERROR` | 配置文件加载失败 |
| `SAVE_ERROR` | 配置文件保存失败 |

### 自动重载

启用文件监控以自动重载配置：

```python
import asyncio
from lemony_settings import init_global_settings, get_global_settings
from lemony_settings.watcher import start_watcher, stop_watcher

async def main():
    # 初始化并启用自动重载
    gs = init_global_settings(preference="toml", config_path="configs")
    gs.persistent.auto_reload = True
    gs.save()
    
    # 启动文件监控
    await start_watcher()
    
    try:
        # 你的应用逻辑
        while True:
            await asyncio.sleep(1)
    finally:
        # 停止监控
        await stop_watcher()

asyncio.run(main())
```

### 手动保存和加载

```python
settings = LemonySettings("my_plugin", "default", MyPluginSettings)

# 手动加载
settings.load()

# 修改配置后手动保存
settings.value.message = "New message"
settings.save()
```

### 使用不同的配置格式

```python
# TOML (默认，推荐)
init_global_settings(preference="toml", config_path="configs")

# YAML
init_global_settings(preference="yaml", config_path="configs")

# JSON
init_global_settings(preference="json", config_path="configs")
```

### 自定义读写器

可以注册自定义的配置文件读写器：

```python
from lemony_settings import ConfigReadWriterABC, register_read_writer
from pathlib import Path
from pydantic import BaseModel

@register_read_writer("ini")
class IniReadWriter(ConfigReadWriterABC):
    def read(self, file: Path, model: type) -> BaseModel:
        # 实现 INI 文件读取
        ...
    
    def write(self, file: Path, data: BaseModel) -> None:
        # 实现 INI 文件写入
        ...
```

## 🔧 API 参考

### 核心类和函数

| 名称 | 说明 |
|------|------|
| `BaseSettings` | 配置模型基类，所有配置类必须继承它 |
| `LemonySettings` | 配置管理器，负责加载、保存和管理配置 |
| `GlobalSettings` | 全局设置，控制整个配置系统的行为 |
| `init_global_settings()` | 初始化全局设置 |
| `get_global_settings()` | 获取全局设置实例 |
| `require()` | 便捷函数，获取配置值 |
| `resolve_config_path()` | 解析配置文件路径 |

### 事件系统

| 名称 | 说明 |
|------|------|
| `SettingsEventType` | 事件类型枚举 |
| `SettingsEvent` | 基础事件类 |
| `SettingsChangeEvent` | 配置变更事件 |
| `SettingsErrorEvent` | 配置错误事件 |
| `SettingsEventEmitter` | 事件发射器 |
| `on_settings_event()` | 事件监听装饰器 |
| `get_event_emitter()` | 获取事件发射器实例 |

### 读写器

| 名称 | 说明 |
|------|------|
| `ConfigReadWriterABC` | 读写器抽象基类 |
| `TomlReadWriter` | TOML 格式读写器 |
| `YamlReadWriter` | YAML 格式读写器 |
| `JsonReadWriter` | JSON 格式读写器 |
| `get_read_writer()` | 获取指定格式的读写器 |
| `register_read_writer()` | 注册自定义读写器的装饰器 |

### 文件监控

| 名称 | 说明 |
|------|------|
| `ConfigFileWatcher` | 配置文件监控器 |
| `start_watcher()` | 启动文件监控 |
| `stop_watcher()` | 停止文件监控 |
| `get_file_watcher()` | 获取文件监控器实例 |

## ⚠️ 注意事项

1. **字段必须有默认值** - `BaseSettings` 的所有字段都必须有默认值，否则初始化会失败
2. **标识符命名规则** - `identifier` 和 `namespace` 必须匹配正则 `^[A-Za-z_][0-9A-Za-z_]{0,31}$`
3. **TOML 不支持 None** - 使用 TOML 格式时，`None` 值会被排除，读取时会自动补全
4. **全局设置只能初始化一次** - `init_global_settings()` 只能调用一次
5. **修改后需手动保存** - 修改配置值后需要调用 `save()` 手动保存到文件
6. **同步事件触发的行为** - 使用 `emit_sync()` 触发事件时，如果没有运行中的事件循环，异步回调会被跳过（仅执行同步回调）

## 🧪 测试

```bash
# 运行所有测试
uv run pytest packages/shared/lemony_settings/tests/ -v

# 运行特定测试文件
uv run pytest packages/shared/lemony_settings/tests/test_core.py -v

# 运行带覆盖率的测试
uv run pytest packages/shared/lemony_settings/tests/ --cov=lemony_settings
```

## 📄 许可证

AGPL-3.0
