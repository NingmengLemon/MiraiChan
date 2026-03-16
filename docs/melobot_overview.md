# melobot 框架概览：独特之处与优势对比

> 本文档综合了 `references/melobot/` 中的源代码与开发者文档，以及 GitHub 仓库最新状态（v3.4.0）。
> 主要对比对象：NoneBot v2、AstrBot。

---

## 一、架构层面：处理流 DAG（最核心的差异）

melobot 使用**有向无环图（DAG）结构**组织事件处理，这是与 NoneBot/AstrBot 最根本的架构差异。

### NoneBot 的模式（线性）

```
事件 → 规则检查 → 处理函数（中间件栈）
```

每个 `matcher` 内部是单一处理函数，最多通过中间件形成线性管道。

### melobot 的模式（DAG 图）

```python
# 可以构造复杂的处理拓扑，来自 references/melobot/src/melobot/handle/graph.py
flow = Flow(
    "complex-flow",
    [[n1, n2], n3, n4, [n5, n6], n7]  # 自动展开为 DAG
)
```

处理流对象内部维护一个真实的 DAG 数据结构，支持深度优先遍历（DFS）、分叉合并、节点复用。

**这带来了什么？**

| 能力 | NoneBot | melobot |
|------|---------|---------|
| 节点复用（同一逻辑段被多条路径共享） | ❌ | ✅ |
| 处理分叉与合并 | 需手动 if-else | ✅ 原生支持 |
| 基于类型注解的节点选择性执行 | ❌ | ✅ |
| 子流嵌套调用 | ❌ | ✅ `flow_to()` |
| 处理流运行期反射 | ❌ | ✅ `FlowRecord` |

---

## 二、处理流控制方法（精细管控执行流程）

melobot 提供了一整套流控制方法（来自 `references/melobot/src/melobot/handle/base.py`）：

```python
from melobot.handle import stop, block, bypass, rewind, nextn, flow_to

@node
async def example_node() -> None:
    await stop()     # 立即终止整个处理流（支持多层函数嵌套内调用）
    await block()    # 阻断事件向更低优先级传播（不影响同级）
    await bypass()   # 跳过当前节点剩余步骤，进入下一节点
    await rewind()   # 重新执行当前节点（与会话搭配实现交互循环）

    with my_context:
        await nextn()  # 控制后继节点的运行时机，运行在自定义上下文环境中
```

NoneBot 中只能通过 `matcher.stop()` / `raise IgnoredException` 等有限手段，且无法精细控制 DAG 遍历。

---

## 三、依赖注入（DI）系统的深度

melobot 的 DI 系统（`references/melobot/src/melobot/di.py`）远比 NoneBot 更深入：

### 3.1 自动依赖项（类型注解即依赖）

```python
# melobot：只需写类型注解
@on_message()
async def handler(event: MessageEvent, bot: Bot, adapter: Adapter, store: FlowStore) -> None: ...

# NoneBot：需要显式 Depends()
async def handler(event: MessageEvent = EventMessage(), bot: Bot = Depends(get_bot)): ...
```

### 3.2 DI 的区分调用（无 isinstance 的类型收窄）

```python
@on_message()
async def handler1(ev: GroupMessageEvent) -> None: ...  # 只有群聊消息触发
@on_message()
async def handler2(ev: PrivateMessageEvent) -> None: ...  # 只有私聊消息触发
```

这是 DAG 节点的**选择性执行机制**，依靠类型不匹配自动跳过节点，无需任何 `isinstance` 判断。

### 3.3 高级 DI 特性

```python
# 递归依赖、子获取器、基于依赖项的依赖
@inject_deps
def f(
    a: Annotated[float, Depends(lambda: 3.14)],
    b: Annotated[int, Depends(dep_a, sub_getter=lambda x: int(x))],  # 子获取器
    c = (_d := Depends(get_val)),
    d = Depends(_d, sub_getter=str),   # 基于已有依赖项的依赖
) -> None: ...
```

### 3.4 反射式依赖注入（会话场景专用）

```python
@on_text(legacy_session=True)
async def handler(event: Annotated[TextEvent, Reflect()]) -> None:
    # event 在每次 suspend() 恢复后自动映射到最新事件，无需重新获取
    city = event.text
    await suspend()
    days = event.text  # 自动是下一条消息的内容
```

---

## 四、多协议多路 IO（真正的多协议并行）

来自 `references/melobot/docs/source/dive_in/source_adapter.md`，这是 melobot 相对于 NoneBot 最独特的架构能力之一。

```python
bot = Bot("multi-protocol-bot")

# 同时绑定 OneBot 多路输入（多账号）
bot.add_io(WSClient(...))   # QQ 账号 A
bot.add_io(WSClient(...))   # QQ 账号 B

# 同时绑定 Telegram 协议（第三方扩展包）
bot.add_io(TelegramSource(...))
bot.add_adapter(TelegramAdapter(...))

# 同时添加控制台协议（本地调试）
bot.add_io(StdioSource())
bot.add_adapter(ConsoleAdapter())
```

| 能力 | NoneBot | melobot |
|------|---------|---------|
| 多协议同时接入 | ❌（同进程内协议独立隔离） | ✅ 同一 bot 实例多协议并行 |
| 同协议多账号 | 需要多个驱动 | ✅ 同一适配器绑定多个源 |
| 跨协议通用行为方法 | ❌ | ✅ `send_text()` 等通用操作自动适配 |
| 通用内容实体 `TextContent` | ❌ | ✅ 屏蔽协议差异的内容层 |

---

## 五、插件 IPC：无导入依赖的跨插件通信

来自 `references/melobot/src/melobot/plugin/ipc.py`：

```python
# 插件 A 声明共享对象（无需被插件 B 导入）
my_data = AsyncShare("user_count")

@my_data
async def get_count() -> int:
    return _count  # 实时反射值

@my_data.setter
async def set_count(val: int) -> None:
    global _count
    _count = val

# 插件 B 从 bot 获取共享对象（无 import 依赖）
share = bot.get_share("plugin_a", "user_count")
count = await share.get()
```

NoneBot 插件间通信通常只能通过直接 `import`（强耦合）或全局状态（不安全）。melobot 的 IPC 机制：

- **异步读写安全**（内部 `RWContext` 读写锁）
- **无导入依赖**（通过名称字符串访问）
- **支持静态共享**（`static=True`，只读值）和**动态共享**（带 setter）

---

## 六、多进程支持（melobot.mp）

来自 `references/melobot/src/melobot/mp.py`，这是 NoneBot/AstrBot 均不具备的能力：

```python
from melobot.mp import SpawnProcess, SpawnProcessPool, PBox

# 安全的多进程任务，自动处理 spawn 模式下的入口点和序列化问题
proc = SpawnProcess(entry="worker.py", target=cpu_bound_task, args=(PBox(my_func),))
proc.start()

# PBox：自定义 pickle 包装器，解决 spawn 模式下的级联加载问题
boxed = PBox(my_function, module="my_module", entry="my_module.py")
```

melobot 劫持了 `multiprocessing.spawn` 的核心函数（`_wrapped_get_preparation_data`），实现了：

- 自定义子进程入口点（避免主脚本在子进程中重新执行）
- 自动重置信号处理（`SIGINT`, `SIGTERM` 子进程由父进程管理）
- `PBox` 通过临时修改对象的 `__module__`/`__qualname__` 属性欺骗 pickle，实现跨进程序列化任意可调用对象

---

## 七、处理流组合式 API（控制反转风格）

```python
# __plugin__.py
test_flow = Flow("test-flow")  # 先声明空流

# flows/step1.py（另一个模块，无需知道全局结构）
@f.after(prev_node)
@node
async def step1(event: MessageEvent) -> None: ...

# flows/step2.py（又另一个模块）
@f.merge(step1, other_node)  # 声明汇聚点
@node
async def final_step() -> None: ...
```

这是一种**控制反转（IoC）** 风格的 API，不需要在一处集中定义所有节点和边，各模块可以独立声明自己对流结构的贡献。NoneBot 没有此类机制。

---

## 八、日志系统的可扩展性

```python
import loguru
from melobot.log import logger_patch

# 将任何第三方日志框架接入 melobot（NoneBot 只支持标准 logging）
loguru_logger = loguru.logger
patched = logger_patch(loguru_logger)
bot = Bot(logger=patched)
```

---

## 九、异常格式化（开发者体验）

melobot 内置了 `better-exceptions` + `rich` 的异常美化渲染（`references/melobot/src/melobot/_render.py`），并：

- 默认隐藏框架内部栈帧，只显示用户代码
- 支持 Jupyter/IPython 环境
- 通过环境变量 `MELOBOT_EXC_SHOW_INTERNAL` / `MELOBOT_EXC_FLIP` 控制格式化风格
- 跨 Python 3.10–3.14 版本兼容同一套 traceback 格式

---

## 十、总结对比

| 特性 | melobot | NoneBot v2 | AstrBot |
|------|---------|------------|---------|
| 处理流架构 | **DAG 图**（可自由搭建） | 线性中间件 | 线性处理 |
| 流控制方法 | stop/block/bypass/rewind/nextn/flow_to | 有限 | 无 |
| 依赖注入 | 深度 DI（自动、递归、反射、子获取器） | 基础 DI | 无 |
| 多协议并行 | **真正多协议同时运行** | 协议隔离 | 多平台适配 |
| 同协议多账号 | **同 bot 多路 IO** | 需多进程 | 部分支持 |
| 跨插件通信 | **AsyncShare/SyncShare（IPC）** | 直接导入 | 无 |
| 插件无序加载 | ✅ | ❌（依赖顺序） | 无 |
| 运行期动态加载插件 | ✅ | 有限支持 | 无 |
| 会话机制 | **suspend()+自定义规则** | 有（相对简单） | 有（AI 对话上下文） |
| 多进程工具 | **SpawnProcess+PBox** | 无 | 无 |
| 日志框架兼容 | 任意框架（logger_patch） | 仅 logging | 仅 logging |
| 组合式流 API | ✅ IoC 风格 | ❌ | ❌ |
| 流运行期反射 | **FlowRecord+FlowStore** | ❌ | ❌ |
| 关注领域 | 通用 bot 框架 | 通用（偏 QQ） | AI 对话优先 |

**一句话总结：**
melobot 的核心优势是其**基于 DAG 的处理流系统**与**深度依赖注入**，使得复杂事件处理逻辑的组织、复用和扩展远超传统线性框架。真正的**多协议多路 IO**并行能力、**IPC 插件通信机制**和**内置多进程工具链**则是其在架构层面区别于其他框架的另外三大独特之处。代价是学习曲线相对较陡，文档中"dive in"部分的内容比 NoneBot 的教程要深得多。

---

*另见：[melobot 预处理机制详解（checker/matcher/parser）](./melobot_preprocess_mechanism.md)*
