# Melobot 框架分析文档

> 本文档总结了对 Melobot 机器人开发框架的研究分析，包括其核心特性、与 FastAPI 相似的依赖注入系统，以及与 NoneBot2/AstrBot 的对比。

## 目录

1. [框架概述](#框架概述)
2. [核心架构：处理流系统](#核心架构处理流系统)
3. [依赖注入系统](#依赖注入系统)
4. [插件系统](#插件系统)
5. [会话控制机制](#会话控制机制)
6. [多协议/多 IO 架构](#多协议多-io-架构)
7. [与 NoneBot2/AstrBot 对比](#与-nonebot2astrbot-对比)
8. [与 FastAPI Depends 对比](#与-fastapi-depends-对比)

---

## 框架概述

Melobot 是一个**跨平台、跨协议、支持多路 IO 及其他高级特性**的 bot 开发框架。其核心设计理念是**自由、优雅和强大**。

### 核心特性

| 特性 | 描述 |
|------|------|
| 处理流系统 | 基于 DAG 的事件处理架构 |
| 依赖注入 | 强大的自动依赖系统 |
| 插件管理 | 无序加载、动态热插拔 |
| 会话控制 | 自动化多轮对话管理 |
| 多协议支持 | OneBot v11、Console 等 |

---

## 核心架构：处理流系统

Melobot 最独特的创新是其**处理流（Flow）系统**，这是一个基于 **DAG（有向无环图）** 的事件处理架构。

### 处理流程

```
事件 → 守卫函数检查 → DAG 遍历 → 处理结点 → 响应
```

### 核心特性

1. **DAG 结构**：事件处理流程可以构建复杂的图结构
2. **热插拔**：支持运行时动态修改处理流
3. **组合式 API**：支持 `.add()`, `.after()`, `.before()`, `.merge()`, `.fork()` 等方法
4. **流控制方法**：
   - `nextn()`: 控制后继结点运行时机
   - `stop()`: 立即终止处理流
   - `block()`: 阻断事件向低优先级传播
   - `bypass()`: 跳过当前结点
   - `rewind()`: 重新运行当前结点
   - `flow_to()`: 进入子流

### 示例代码

```python
from melobot import Bot, PluginPlanner, on_start_match, send_text
from melobot.handle import node, Flow

# 简单用法
@on_start_match(".sayhi")
async def echo_hi() -> None:
    await send_text("Hello, melobot!")

# 高级用法：构建复杂 DAG
n1 = node(step1)
n2 = node(step2)
flow = Flow("my-flow", [n1, n2])
flow.update_priority(10)  # 运行时调整优先级
```

---

## 依赖注入系统

Melobot 的依赖注入系统与 FastAPI 高度相似，但功能更加强大。

### 支持的两种写法

#### 1. 默认值写法

```python
from melobot.di import inject_deps, Depends

def get_current_user() -> str:
    ...

@inject_deps
def func(s = Depends(get_current_user)) -> None:
    print(f"用户: {s}")
```

#### 2. Annotated 写法（推荐）

```python
from typing import Annotated
from melobot.di import inject_deps, Depends

@inject_deps
def func(s: Annotated[str, Depends(get_current_user)]) -> None:
    print(f"用户: {s}")
```

### 独有特性

1. **依赖缓存**：`Depends(get_val, cache=True)`
2. **递归依赖**：依赖可以依赖其他依赖，自动链式满足
3. **子获取器**：`Depends(get_val, sub_getter=lambda d: d["key"])`
4. **自动依赖项**：直接通过类型注解获取 Bot、Adapter、Event 等

### 自动依赖项列表

| 类型注解 | 对应依赖 |
|---------|---------|
| `Bot` | 当前 bot 实例 |
| `Adapter` | 当前适配器 |
| `MessageEvent` | 当前事件 |
| `Logger` | 日志器 |
| `FlowStore` | 流存储 |
| `Session` | 会话对象 |

---

## 插件系统

Melobot 的插件系统采用独特的设计理念。

### 特性

| 特性 | 描述 |
|------|------|
| 无序加载 | 依赖自动满足，无需声明加载顺序 |
| 动态加载 | 支持运行时加载/卸载插件 |
| 跨插件通信 | 共享对象 + 导出函数 |
| 插件隔离 | 完全隔离的插件环境 |

### 示例

```python
# 匿名插件
test_plugin = PluginPlanner(version="1.0.0", flows=[echo_hi])

# 模块级插件 + 组合式 API
ECHO_PLUGIN = PluginPlanner(version="1.0.0")

@ECHO_PLUGIN.use  # 控制反转
@on_start_match(".sayhi")
async def echo_hi() -> None:
    pass
```

---

## 会话控制机制

Melobot 提供强大的多轮对话支持。

```python
from melobot.session import enter_session, Session, SessionRule

@on_message(checker=some_checker)
@ctx(lambda: enter_session(rule))
async def session_handler(session: Session, store: SessionStore):
    # 会话存储在整个会话期间持久
    store["key"] = value
    await session.pause()  # 暂停会话
    # 下次相同会话继续执行
```

---

## 多协议/多 IO 架构

Melobot 的协议层设计理念独特：**所有协议都是 IO 过程**。

```
┌─────────────────────────────────────────────┐
│              协议 (Protocol)                  │
├─────────────────────────────────────────────┤
│  输入源 ──> 输入包 ──> 适配器 ──> 事件       │
│  适配器 ──> 行为 ──> 输出包 ──> 输出源       │
└─────────────────────────────────────────────┘
```

### 跨协议 IO 能力

- **多协议同时在线**：同时连接多个协议端
- **自由输出**：可以指定输出到特定协议端
- **协议即插即用**：编写新协议支持只需实现 Source 和 Adapter

---

## 与 NoneBot2/AstrBot 对比

### NoneBot2

| 维度 | Melobot | NoneBot2 |
|------|---------|----------|
| 事件处理结构 | DAG（可复杂组合） | 线性 Matcher 链 |
| 流控制 | 6种控制方法 | 简单的 block |
| 动态性 | 支持热插拔 | 静态注册 |
| 社区生态 | 较小 | 更大更成熟 |

### AstrBot

| 维度 | Melobot | AstrBot |
|------|---------|----------|
| 定位 | 开发框架 | 开箱即用的产品 |
| 复杂度 | 需要开发能力 | 插件生态丰富 |
| 灵活性 | 极高 | 中等 |
| LLM 集成 | 需自行实现 | 原生支持 |

---

## 与 FastAPI Depends 对比

| 特性 | Melobot | FastAPI |
|------|---------|---------|
| 基本 Depends | ✅ 支持 | ✅ 支持 |
| Annotated 写法 | ✅ 支持 | ✅ 支持 |
| 依赖缓存 | ✅ `cache=True` | ✅ 需手动实现 |
| 递归依赖 | ✅ 自动递归 | ❌ 不支持 |
| 子获取器 | ✅ `sub_getter` | ❌ 不支持 |
| 自动依赖项 | ✅ 丰富 | ❌ 需手动获取 |
| 多层装饰穿透 | ✅ 完整支持 | ⚠️ 有限支持 |

---

## 适用场景

### 推荐使用 Melobot

- ✅ 需要**复杂事件处理流程**的应用
- ✅ 需要**高度定制化**的机器人逻辑
- ✅ 需要**多个协议同时在线**
- ✅ 需要**强大的会话管理**
- ✅ 追求**优雅的代码架构**

### 建议选择其他框架

- **NoneBot2**：社区更大，插件更丰富
- **AstrBot**：需要开箱即用的 LLM 助手
