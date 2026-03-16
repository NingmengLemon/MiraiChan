# Melobot Matcher、Parser、Checker 机制与权限设计

> 本文档详细分析了 Melobot 框架中的事件处理机制，以及 LemonyChecker 权限检查器的设计讨论。

---

## 目录

1. [事件处理流程](#事件处理流程)
2. [各组件职责](#各组件职责)
3. [依赖注入时机](#依赖注入时机)
4. [fail_cb 使用指南](#fail_cb-使用指南)
5. [LemonyChecker 设计讨论](#lemonychecker-设计讨论)

---

## 事件处理流程

在 Melobot 中，事件处理的完整流程如下：

```
事件到达 → 守卫函数(guard) → Matcher匹配 → Parser解析 → Handler执行
          ↓                ↓            ↓
        Checker       文本匹配       参数解析
```

### 关键代码位置

`handle/register.py` 中的 `FlowDecorator` 类：

```python
# 1. 守卫函数（Guard）- 包含 Checker 检查
async def _guard(self, event: Event) -> bool:
    if self.checker:
        status = await self.checker.check(event)  # 先执行 Checker
        if not status:
            return False
    
    if self.matcher:
        event = cast(TextEvent, event)
        status = await self.matcher.match(event.text)  # 再执行 Matcher
        if not status:
            return False
    return True

# 2. 流包装函数 - 包含 Parser 解析
async def _flow_wrapped(self, func, ...):
    passed, args = await self._parse(completion.event)  # Parser 解析
    if not passed:
        return None
    return await self._process(func, completion, args)  # 最后执行 Handler

# 3. 依赖注入时机
# 在创建 FlowNode 时已经通过 inject_deps 装饰：
func = inject_deps(func, avoid_repeat=True)
n = FlowNode(...)
```

---

## 各组件职责

| 组件 | 位置 | 职责 | 失败后果 |
|------|------|------|---------|
| **Checker** | `_guard()` | 权限检查、用户验证等 | 跳过该处理流 |
| **Matcher** | `_guard()` | 文本匹配（startswith/contains/regex等） | 跳过该处理流 |
| **Parser** | `_flow_wrapped()` | 命令参数解析 | 跳过该处理流 |
| **Handler** | `_process()` | 实际业务逻辑 | 处理完成 |

---

## 依赖注入时机

在 Melobot 中，依赖注入的时机如下：

1. **类型检查** → 2. **Checker 检查** → 3. **Matcher 匹配** → 4. **Parser 解析** → 5. **Handler 执行（依赖注入已完成）**

依赖注入发生在 Handler 执行之前，通过 `inject_deps` 装饰器完成：

```python
func = inject_deps(func, avoid_repeat=True)
n = FlowNode(...)
```

这意味着在 Handler 函数内部可以直接使用自动依赖注入：

```python
@on_start_match(".admin")
async def admin_handler(bot: Bot, event: MessageEvent, logger: Logger):
    # 依赖注入已完成，可以直接使用
    pass
```

---

## fail_cb 使用指南

### 问题分析

如果在 `Checker` 的 `fail_cb` 中放置拒绝消息（如"权限不足"），会导致：

- 每个不满足 Checker 条件的消息都会触发回复
- 正常消息也会触发（只是 Checker 通过了，但 fail_cb 会在失败时触发）

### 解决方案

#### 方案 1：使用 Handler 内部判断（推荐）

```python
@on_start_match(".admin", checker=OwnerChecker())
async def admin_handler():
    # 权限检查通过，可以执行管理命令
    await send_text("执行管理操作")
```

#### 方案 2：使用多层处理流 + 优先级

```python
# 低优先级流 - 处理拒绝回复
@on_start_match(".do_something", priority=0)
async def reject_handler():
    if not should_reject:
        return
    await send_text("权限不足")

# 高优先级流 - 处理正常请求  
@on_start_match(".do_something", priority=10, block=True)
async def accept_handler():
    await send_text("操作成功")
```

#### 方案 3：使用 Rule 会话机制

```python
from melobot.session import Rule

class PermissionRule(Rule):
    async def check(self, event) -> bool:
        result = has_permission(event)
        if not result:
            await send_text("权限不足")
        return result
```

### fail_cb 适用场景

| 场景 | 建议 |
|------|------|
| 日志记录 | ✅ 适合 |
| 统计计数 | ✅ 适合 |
| 发送拒绝消息 | ❌ 不推荐 |

---

## LemonyChecker 设计讨论

### 当前设计

LemonyChecker 实现了完整的权限检查系统：

- `LemonyCheckerFactory` - 工厂类，管理配置
- `LemonyChecker` - 实际的 Checker 实现
- `_CheckerFactoryWrapper` - 包装类，方便链式调用

### Checker 形式的优缺点

#### ✅ 优点

1. **与 Melobot 生态契合** - Checker 是官方推荐方式
2. **可组合** - 可以用 `&` `|` `~` 运算符组合
3. **配置驱动** - 通过 Factory + lemony_settings 管理
4. **权限体系完整** - Owner/Admin/白名单/黑名单

#### ⚠️ 缺点

1. fail_cb 粒度粗 - 无法区分不同场景
2. 权限检查与消息发送耦合

### 建议：权限检查节点

可以将权限检查作为处理流中的一个普通节点：

```python
from melobot.handle import node
from melobot.di import inject_deps

@node
async def check_permission(
    event: MessageEvent,
    factory: LemonyCheckerFactory = inject_deps,
    plugin_name: str = "default",
    fail_message: str = "权限不足",
):
    """权限检查节点
    
    返回 True 表示检查通过，继续执行后续节点
    返回 False 表示检查失败，已发送拒绝消息，跳过后续节点
    """
    checker = factory.new_checker(plugin_name=plugin_name, fail_cb=None)
    passed = await checker.check(event)
    
    if not passed:
        await send_text(fail_message)
        return False
    
    return True
```

使用方式：

```python
@on_start_match(".do_something")
@check_permission(plugin_name="my_plugin", fail_message="你没有权限使用这个命令")
async def do_something():
    await send_text("命令执行成功")
```

---

## 总结

1. **Melobot 处理流程**：Checker → Matcher → Parser → Handler
2. **fail_cb 使用**：适合日志/统计，不适合发送拒绝消息
3. **LemonyChecker**：当前设计可用，建议在 handler 内部决定是否发送拒绝消息
