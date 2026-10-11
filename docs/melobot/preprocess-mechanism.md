# melobot 预处理机制详解：checker / matcher / parser

> 本文档基于 melobot 3.5.0，依据 `references/melobot/src/melobot/handle/register.py`、
> `references/melobot/src/melobot/handle/base.py`、`references/melobot/src/melobot/utils/check/base.py` 以及
> `references/melobot/src/melobot/protocols/onebot/v11/utils/check.py` 的源代码分析。

---

## 一、整体处理管道

在开始执行 handler 函数之前，melobot 经历如下几个阶段（以 `FlowDecorator` 即 `on_message()`、`on_text()`、`on_start_match()` 等流装饰器为例）：

```
事件到来
    │
    ▼ 阶段 1：守卫（Guard，Flow._run 在流上下文中调用）
    ├── checker.check(event)   ← 先运行 checker
    │       └─ False → 流不运行（MsgChecker 等在消息事件上会触发 fail_cb）
    ├── matcher.match(event.text)  ← checker 通过后才运行 matcher
    │       └─ False → 流不运行
    │
    ▼ 阶段 2：解析（Parse，在结点内部）
    ├── parser.parse(event.text)   ← 在结点函数体内、DI 之前
    │       └─ None → 结点返回 None（流停止）
    │       └─ args → 注入 ParseArgsCtx，供 DI 获取
    │
    ▼ 阶段 3：会话创建（如果有 rule / legacy_session）
    ├── async with enter_session(rule):
    │
    ▼ 阶段 4：用户函数执行
        ├── 依赖注入  ← DI 在调用用户函数时发生
        └── 用户函数体
```

关键点：checker 先于 matcher 在守卫阶段运行。只要事件类型符合流装饰器的要求，就会先经过 checker，与 matcher 是否匹配无关。

---

## 二、各阶段详解

### 2.1 守卫阶段（Guard）

源码位置：`FlowDecorator._guard()` 方法

```python
async def _guard(self, event: Event) -> bool:
    if self.checker:
        status = await self.checker.check(event)
        if not status:
            return False           # ← checker 失败则守卫失败

    if self.matcher:
        event = cast(TextEvent, event)
        status = await self.matcher.match(event.text)
        if not status:
            return False           # ← matcher 失败则守卫失败

    return True
```

- checker 接收完整的 `Event` 对象，可以检查权限、来源等任意属性
- matcher 只接收 `event.text`（字符串），仅检查文本内容
- 守卫阶段没有依赖注入，没有会话状态
- 守卫失败时整个处理流不会运行（该事件的其他处理流不受影响）；守卫函数抛出异常时记录日志并同样视为不运行

`on_text()` / `on_start_match()` 等方法会用 `checker_join(lambda e: isinstance(e, TextEvent), user_checker)` 将"是否为文本事件"的检查和用户提供的 checker 合并成一个 AND 检查器（OneBot v11 的 `on_message()` 等同理，检查 `MessageEvent`）。因此类型不符的事件在守卫阶段的第一步就被过滤，不会进入用户 checker。

### 2.2 解析阶段（Parse）

源码位置：`FlowDecorator._parse()` 方法

```python
async def _parse(self, event: Event) -> tuple[bool, AbstractParseArgs | None]:
    args: AbstractParseArgs | None = None
    if self.parser:
        event = cast(TextEvent, event)
        args = await self.parser.parse(event.text)
        if args is not None:
            return (True, args)
        return (False, None)

    return (True, None)
```

- parser 在守卫通过后、用户函数执行前调用
- 解析成功：args 通过 `ParseArgsCtx().add(args)` 存入上下文，供 DI 获取
- 解析失败（返回 `None`）：结点直接返回，流停止（效果等同于守卫失败）
- 解析阶段同样没有依赖注入
- `block=True` 时，事件的 `spread` 在解析通过之后才被置为 `False`，解析失败不会阻断低优先级传播

### 2.3 依赖注入阶段（DI）

DI 发生在用户函数被调用时，此时以下对象可通过类型注解自动注入：

| 类型注解 | 可获取的对象 |
|---------|------------|
| `Event` / 子类 | 当前事件（会话中用 `ref()` 或 `Annotated[..., Reflect()]` 获取最新事件） |
| `Bot` | 当前 bot 实例 |
| `Adapter` / 子类 | 协议适配器（配合 `match_event()` 取产生当前事件的适配器） |
| `GenericLogger` | 当前日志器 |
| `FlowStore` | 当前处理流的流存储 |
| `tuple[FlowRecord, ...]` | 当前处理流的流记录（需 `Flow.enable_record()` 后才有内容） |
| `Session` | 当前会话对象（需要进入会话后才存在） |
| `SessionStore` | 当前会话存储（同上） |
| `Rule` | 当前会话规则（同上） |
| `AbstractParseArgs` / 子类 | 解析结果（parser 解析后才存在） |

除类型注解外，还可以用默认值形式的依赖项：`get_flow_arg(key, verify=..., type=..., default=...)` 从流存储取值，`get_session_arg(...)` 从会话存储取值，`get_cmd_arg(idx)`（`melobot.utils.parse`）取 `CmdArgs` 中的单个参数。

### 2.4 `node()` 装饰器内的顺序

`node(etype=..., checker=..., matcher=..., parser=...)` 形式的结点装饰器内部顺序与 `FlowDecorator` 基本一致（来自 `node_wrapped` 函数）：

```
etype isinstance 检查 → checker → matcher → parser → [block] → [legacy_session] → 用户函数（DI）
```

不同之处：这些检查都在结点内部运行（不是守卫函数），任何一步失败都返回 `False`，使结点不执行后继结点。`node` 的 matcher / parser 不会自动校验事件是否为文本事件，需要配合 `etype` 或 checker 自行保证。

---

## 三、fail_cb 的触发条件与正确用法

### 3.1 `MsgChecker.fail_cb` 的触发条件

源码（`references/melobot/src/melobot/protocols/onebot/v11/utils/check.py` 第 152-154 行）：

```python
finally:
    if not status and is_msg and self.fail_cb is not None:
        await self.fail_cb()
```

触发 `fail_cb` 需要同时满足：

1. `not status`：检查未通过
2. `is_msg`：当前事件是消息事件（notice/request/meta 事件不触发）

`MsgChecker` 会把同一事件的检查结果缓存在事件的 flag 上，但 `fail_cb` 写在 `finally` 里，命中缓存时同样会执行。也就是说，同一事件经过多个使用同一检查器配置的处理流时，每个流都会触发一次 `fail_cb`。

这意味着，对于一个有 `checker=OWNER_CHECKER` 的处理流，所有消息事件（无论是否匹配 matcher）都会先经过 checker。如果权限不足，`fail_cb` 就会被触发。

### 3.2 "拒绝回复导致每条消息都触发"的问题

假设有这样的处理流：

```python
@on_start_match(".admin", checker=MsgChecker(LevelRole.OWNER, ..., fail_cb=deny_reply))
async def admin_cmd(): ...
```

执行流程分析：

| 消息内容 | 发送者权限 | 执行路径 |
|---------|-----------|---------|
| `.admin xxx` | OWNER | checker 通过 → matcher 通过 → 执行 handler |
| `.admin xxx` | 普通用户 | checker 失败 → 触发 fail_cb（回复"权限不足"）→ matcher 不运行 |
| `普通消息` | OWNER | checker 通过 → matcher 失败（不以 `.admin` 开头）→ 不执行 |
| `普通消息` | 普通用户 | checker 失败 → 触发 fail_cb（回复"权限不足"）→ 流停止 |

问题在最后一行：普通用户发送任何普通消息（如"好的"、"谢谢"），都会触发 `fail_cb` 并回复"权限不足"。

根本原因是守卫阶段 checker 先于 matcher 执行。

---

## 四、拒绝回复应该放在哪里

以下示例中 `on_start_match` 来自 `melobot.handle`（也可从 `melobot` 顶级导入），OneBot 事件与检查器来自 `melobot.protocols.onebot.v11`。

### 方案 1（推荐）：在 handler 函数内部检查

不使用 checker，直接在函数体里判断权限并决定是否回复：

```python
from melobot import on_start_match, send_text
from melobot.protocols.onebot.v11 import MessageEvent


@on_start_match(".admin")
async def admin_cmd(event: MessageEvent) -> None:
    if event.sender.user_id != OWNER_QID:
        await send_text("权限不足，该功能仅限管理员使用。")
        return
    # 实际逻辑...
```

优点：逻辑清晰，只有以 `.admin` 开头的消息才会进入处理，也才有可能触发拒绝回复。

### 方案 2（推荐）：高优先级"拒绝"流

用两个处理流分离"过滤"和"执行"：

```python
# 高优先级（1）：专门负责拒绝回复
# 先经过 matcher 确认是目标命令，再在函数内检查权限
@on_start_match(".admin", priority=1)
async def admin_deny(event: MessageEvent) -> None:
    if event.sender.user_id != OWNER_QID:
        await send_text("权限不足！")
        # 不需要 block()，因为低优先级流有 checker 过滤


# 低优先级（0）：带 checker，只有权限足够才执行
@on_start_match(".admin", priority=0, checker=lambda e: e.sender.user_id == OWNER_QID)
async def admin_cmd() -> None:
    # 实际逻辑
    ...
```

### 方案 3：fail_cb 里自行检查 matcher 条件

如果一定要用 `fail_cb`，在回调里手动检查消息是否匹配命令前缀：

```python
from melobot import TextEvent, on_start_match, send_text
from melobot.handle import get_event
from melobot.protocols.onebot.v11 import LevelRole, MsgChecker


async def deny_if_admin_cmd() -> None:
    event = get_event()
    # 只有确实在尝试使用管理命令时才回复
    if isinstance(event, TextEvent) and event.text.startswith(".admin"):
        await send_text("权限不足，该功能仅限管理员使用。")


@on_start_match(".admin", checker=MsgChecker(LevelRole.OWNER, ..., fail_cb=deny_if_admin_cmd))
async def admin_cmd() -> None:
    ...
```

缺点：fail_cb 里重复了 matcher 的逻辑，有些冗余。但在需要保持 checker 独立复用的场景下是可行的。

### 方案 4：fail_cb 里放非回复操作

`fail_cb` 最适合做不依赖消息内容的副作用，例如：

```python
import logging


def log_denied() -> None:
    logging.debug("权限检查未通过")


def count_denied() -> None:
    denied_counter.increment()  # 统计被拒绝次数


@on_start_match(".admin", checker=MsgChecker(LevelRole.OWNER, ..., fail_cb=log_denied))
async def admin_cmd() -> None:
    ...
```

### 4.1 MiraiChan 当前权限层的推荐分层

基于上述机制，`lemony_checkers`（`packages/shared/lemony_checkers/src/lemony_checkers/`）采用三层接口：

1. `core.py`：框架无关的权限判定函数。输入已经提取好的 `UniqueUser`、全局配置、插件配置，输出布尔结果或规则匹配结果；这里不导入 melobot，也不关心事件对象。
2. `nodes.py`：melobot 推荐入口。`@require_permission` / `@require_admin` / `@require_owner` 适合普通 `@on_command` 等 handler；`PermissionNodeFactory` 适合手写复杂 `Flow` 时把权限检查作为 DAG 中的显式结点。
3. `checkers.py`：兼容 melobot `Checker` 的低级适配层。它可以继续参与 `checker | checker` 这种组合，但不建议把用户可见的拒绝回复放到 checker `fail_cb` 中。

`@require_permission` 放在 `@on_command` 与 handler 之间时不会破坏 melobot 的依赖注入，前提是装饰器内部保留 `functools.wraps(handler)`：melobot 在 `FlowDecorator.__call__` 中对收到的函数执行 `inject_deps(func, avoid_repeat=True)`，而 `inspect.signature()` 会沿着 `__wrapped__` 读取原始 handler 的签名。因此 DI 仍然能看到 `event: GroupMessageEvent`、`adapter: Adapter`、`logger: GenericLogger` 等原始参数注解；运行时 wrapper 会先收到这些已注入参数，再从参数中提取事件并执行权限检查。

```python
@MoeLottery.use
@on_command(".", " ", ["今日人设"])
@require_permission(PLUGIN_IDENTIFIER, "draw_attrs")
async def draw_attrs(event: GroupMessageEvent, adapter: Adapter, logger: GenericLogger):
    ...
```

这个顺序的实际效果是：命令解析先通过，DI 注入参数，然后 `require_permission` 的 wrapper 执行权限判定。拒绝回复只会发生在真正匹配该命令的消息上，不会落入 checker/fail_cb 的"所有消息先检查"陷阱。

---

## 五、`WrappedChecker` 的 fail_cb（逻辑运算后）

当使用 `|`、`&`、`^`、`~` 合并检查器时，产生的 `WrappedChecker` 有自己的 `fail_cb`，构造时为空，通过 `.set_fail_cb()` 设置：

```python
from melobot.utils.check import WrappedChecker

combined: WrappedChecker = checker_a | checker_b
combined.set_fail_cb(some_callback)
```

`WrappedChecker.check()` 源码（`utils/check/base.py` 第 97-112 行）：

```python
async def check(self, event: EventT) -> bool:
    match self.mode:
        case LogicMode.AND:
            status = await self.c1.check(event) and await self.c2.check(event)
        case LogicMode.OR:
            status = await self.c1.check(event) or await self.c2.check(event)
        # ...

    if not status and self.fail_cb is not None:
        await self.fail_cb()    # ← WrappedChecker 的 fail_cb 在逻辑运算结果为 False 时触发
    return status
```

注意：

- `WrappedChecker` 的 `fail_cb` 没有 `is_msg` 过滤，任何事件类型只要整体逻辑运算结果为 False 就会触发。
- 被合并的子检查器各自的 `fail_cb` 依然会在其 `check()` 内触发。AND / OR 是短路求值，被短路跳过的子检查器不会运行，其 `fail_cb` 也不会触发。
- 流装饰器内部的 `checker_join` 同样产生 `WrappedChecker`（AND 模式），但不设置 `fail_cb`；用户 checker 的 `fail_cb` 照常生效。

---

## 六、`checker` 的执行上下文

在守卫阶段，`checker.check(event)` 被调用时：

- 不在 DI 上下文中（`Checker.new()` 只把函数包装为异步函数，不做依赖注入）
- 不在会话上下文中
- 可以使用 `get_event()`、`get_bot()` 等上下文方法（`Flow._run` 在流上下文中调用守卫函数）

fail_cb（在 checker 内部触发）也处于同样的上下文中，可以使用 `get_event()`，但不支持依赖注入。

---

## 七、总结

| 阶段 | 运行内容 | 顺序 | 是否有 DI | fail_cb 触发条件 |
|------|---------|------|---------|----------------|
| 守卫（Guard） | checker | 第 1 步 | 否 | MsgChecker 等：检查未通过且为消息事件；WrappedChecker：结果为 False |
| 守卫（Guard） | matcher | 第 2 步（checker 通过后） | 否 | 无 fail_cb |
| 结点内 | parser | 第 3 步（进入结点后） | 否 | 无 fail_cb |
| 结点内 | 会话创建 | 第 4 步（parser 通过后） | 否 | 无 |
| 结点内 | 用户函数 | 第 5 步 | 是 | 无 |

关于拒绝回复的建议：

- 拒绝回复放在 handler 函数体内（最简单清晰），或用 `lemony_checkers` 的 `@require_permission` 等装饰器
- 拒绝回复放在高优先级专用处理流内（matcher 过滤后再检查权限）
- fail_cb 内放拒绝回复需要在回调里自行检查 matcher 条件，容易出错
- fail_cb 更适合放日志、统计等不依赖消息内容的副作用

---

*另见：[melobot 框架概览与优势对比](./overview.md)*
