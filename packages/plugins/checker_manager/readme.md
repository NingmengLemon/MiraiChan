# Checker Manager

MiraiChan 插件：用于让 Owner 和管理员从聊天通过指令管理 `lemony_checkers` 包中的过滤规则。

## 功能

- 全局规则管理（用户规则、群组规则）
- 全局权限模式设置（白名单/黑名单）
- 管理员管理（添加/移除）
- 插件级别规则管理
- 配置重载与保存

## 指令列表

### 状态查看

```
.checker status                             - 查看当前状态
```

### 全局配置

```
.checker global mode <whitelist|blacklist>  - 设置全局权限模式
.checker global rules [user|group]          - 查看全局规则
.checker global add <user|group> <allow|deny> [id1,id2,...] - 添加全局规则
.checker global remove <user|group> <index> - 移除全局规则
.checker global clear [user|group]          - 清除全局规则
```

### 管理员管理（仅 Owner）

```
.checker admin list                         - 查看管理员列表
.checker admin add <user_id>                - 添加管理员
.checker admin remove <user_id>             - 移除管理员
```

### 插件配置

```
.checker plugin <name> enable               - 启用插件
.checker plugin <name> disable              - 禁用插件
.checker plugin <name> mode <whitelist|blacklist|inherit> - 设置插件权限模式
.checker plugin <name> rules [user|group]   - 查看插件规则
.checker plugin <name> add <user|group> <allow|deny> [id1,id2,...] - 添加插件规则
.checker plugin <name> remove <user|group> <index> - 移除插件规则
.checker plugin <name> clear [user|group]   - 清除插件规则
```

### 配置管理

```
.checker reload [global|<plugin_name>]      - 重新加载配置
.checker save [global|<plugin_name>]        - 保存配置
```

## 权限要求

- 大部分操作需要 Owner 或 Admin 权限
- 管理员的增删操作仅 Owner 可用

## 示例

```
# 查看状态
.checker status

# 设置全局黑名单模式
.checker global mode blacklist

# 添加全局用户禁止规则
.checker global add user deny 123456,789012

# 添加全局群组允许规则（匹配所有群）
.checker global add group allow

# 查看全局规则
.checker global rules

# 添加管理员
.checker admin add 123456

# 禁用某个插件
.checker plugin my_plugin disable

# 为插件设置白名单模式
.checker plugin my_plugin mode whitelist

# 为插件添加用户允许规则
.checker plugin my_plugin add user allow 123456,789012
```
