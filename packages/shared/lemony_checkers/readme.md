# Lemony Checkers

一个基于配置的权限检查库，专为 MiraiChan 设计。使用 `lemony_settings` 进行配置管理，支持全局规则和插件特定规则。

## ✨ 特性

- 🔐 **灵活的权限控制** - 支持白名单/黑名单模式
- 📋 **分层规则系统** - 全局规则 + 插件特定规则
- 👑 **特权用户** - Owner 和 Admin 角色支持
- 🎛️ **命令级控制** - 精细到命令级别的启停管理
- 💾 **配置持久化** - 使用 `lemony_settings` 自动保存和重载
- 🔌 **易于集成** - 与 melobot 无缝配合

## 📦 安装

```bash
# 作为工作区依赖
uv add lemony_checkers
```

## 🚀 快速开始

### 1. 初始化配置系统

在程序启动时初始化 `lemony_settings`：

```python
from lemony_settings import init_global_settings

# 初始化全局设置
init_global_settings(preference="toml", config_path="configs")
```

### 2. 使用检查器

```python
from lemony_checkers import LemonyChecker, OwnerChecker, AdminChecker
from melobot.protocols.onebot.v11 import on_message, on_command
from melobot import send_text

# 基本用法 - 只使用全局规则
@on_message(checker=LemonyChecker())
async def handler():
    await send_text("通过权限检查!")

# 插件级别检查器
@on_command(".", " ", "echo", checker=LemonyChecker(plugin_name="my_plugin"))
async def echo_handler():
    await send_text("Echo!")

# 命令级别检查器
@on_command(".", " ", "admin_cmd", checker=LemonyChecker(
    plugin_name="my_plugin",
    command_name="admin_cmd"
))
async def admin_cmd_handler():
    await send_text("Admin command executed!")

# Owner 专用
@on_command(".", " ", "restart", checker=OwnerChecker())
async def restart_handler():
    await send_text("Restarting...")

# Admin 检查器 (Owner 和 Admin 都可通过)
@on_command(".", " ", "manage", checker=AdminChecker())
async def manage_handler():
    await send_text("Management command!")
```

### 3. 带失败回调的检查器

```python
from melobot.protocols.onebot.v11 import MessageEvent

async def on_permission_denied(event: MessageEvent):
    await send_text("❌ 你没有权限使用此功能")

checker = LemonyChecker(
    plugin_name="my_plugin",
    fail_cb=on_permission_denied
)

@on_command(".", " ", "secret", checker=checker)
async def secret_handler():
    await send_text("Secret content!")
```

## ⚙️ 配置文件

配置文件会自动创建在 `configs/lemony_checkers/` 目录下。

### 全局配置 (`configs/lemony_checkers/global.toml`)

```toml
# 权限模式: "whitelist" 或 "blacklist"
# - whitelist: 默认拒绝，只允许规则中明确允许的
# - blacklist: 默认允许，只拒绝规则中明确拒绝的
mode = "blacklist"

# 机器人所有者 QQ 号 (无视所有权限检查)
owner = 123456789

# 管理员 QQ 号列表
admins = [111111111, 222222222]

# 全局规则
[rules]
# 私聊规则 (按用户 ID 匹配)
[[rules.private]]
action = "deny"
ids = [666666666]  # 黑名单用户

[[rules.private]]
action = "allow"
ids = [777777777, 888888888]  # 白名单用户

# 群聊规则 (按群组 ID 匹配)
[[rules.group]]
action = "allow"
ids = [987654321]  # 允许的群组

[[rules.group]]
action = "deny"
ids = [123123123]  # 禁止的群组
```

### 插件配置 (`configs/lemony_checkers/{plugin_name}.toml`)

```toml
# 插件是否启用
enabled = true

# 插件的权限模式 (为空时使用全局配置)
# mode = "whitelist"

# 插件特定规则
[rules]
[[rules.private]]
action = "allow"
ids = [999999999]

[[rules.group]]
action = "deny"
ids = [111222333]

# 命令启用状态
[commands]
echo = true
secret = false  # 禁用 secret 命令
admin_cmd = true
```

## 🔄 检查流程

```
用户发送消息
    ↓
melobot 接收事件
    ↓
LemonyChecker.check()
    │
    ├─ 是 Owner? ──────────────→ ✅ 通过
    │
    ├─ 插件已禁用? ─────────────→ ❌ 拒绝
    │
    ├─ 命令已禁用? ─────────────→ ❌ 拒绝
    │
    ├─ 是 Admin 且 allow_admin? → ✅ 通过
    │
    ├─ 匹配全局规则?
    │   ├─ ALLOW ───────────────→ ✅ 通过
    │   └─ DENY ────────────────→ ❌ 拒绝
    │
    ├─ 匹配插件规则?
    │   ├─ ALLOW ───────────────→ ✅ 通过
    │   └─ DENY ────────────────→ ❌ 拒绝
    │
    └─ 默认行为 (根据 mode)
        ├─ whitelist ───────────→ ❌ 拒绝
        └─ blacklist ───────────→ ✅ 通过
    ↓
[如果拒绝且有 fail_cb]
    ↓
执行 fail_cb(event)
```

## 📖 API 参考

### 检查器类

| 类名 | 说明 |
|------|------|
| `LemonyChecker` | 主检查器，支持全局和插件规则 |
| `OwnerChecker` | Owner 专用检查器 |
| `AdminChecker` | Admin 检查器 (Owner 和 Admin 都可通过) |

### LemonyChecker 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `plugin_name` | `str \| None` | `None` | 插件名称，用于加载插件配置 |
| `command_name` | `str \| None` | `None` | 命令名称，用于命令级启停控制 |
| `fail_cb` | `Callable` | `None` | 检查失败时的回调函数 |
| `allow_admin` | `bool` | `True` | 是否允许 Admin 通过检查 |

### 辅助函数

| 函数 | 说明 |
|------|------|
| `is_owner(user_id)` | 检查用户是否是 Owner |
| `is_admin(user_id)` | 检查用户是否是 Admin |
| `get_owner()` | 获取 Owner QQ 号 |
| `get_admins()` | 获取 Admin 列表 |
| `get_checker_global_settings()` | 获取全局配置 |
| `get_checker_plugin_settings(name)` | 获取插件配置 |
| `reload_global_settings()` | 重新加载全局配置 |
| `reload_plugin_settings(name)` | 重新加载插件配置 |

## 📝 配置模型

### CheckerGlobalSettings

```python
class CheckerGlobalSettings(BaseSettings):
    mode: Literal["whitelist", "blacklist"] = "blacklist"
    owner: int | None = None
    admins: list[int] = []
    rules: RuleSet = RuleSet()
```

### CheckerPluginSettings

```python
class CheckerPluginSettings(BaseSettings):
    enabled: bool = True
    mode: Literal["whitelist", "blacklist"] | None = None
    rules: RuleSet = RuleSet()
    commands: dict[str, bool] = {}
```

### Rule

```python
class Rule(BaseModel):
    action: Literal["allow", "deny"]
    ids: list[int] = []  # 空列表表示匹配所有
```

## 🔗 依赖

- `lemony_settings` - 配置管理
- `melobot[onebot]` - 机器人框架
- `pydantic` - 数据验证

## 📄 许可证

AGPL-3.0
