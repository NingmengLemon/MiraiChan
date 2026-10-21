# melobot 框架概览：独特之处与优势对比

> 本文档基于 melobot 3.5.1，综合了 `references/melobot/src/melobot` 的源代码与 `references/melobot/docs/source` 的开发者文档。
> 主要对比对象：NoneBot v2、AstrBot。对比对象一侧的描述未逐条对照其源码核实，仅作定性参考。

---

## 一、架构层面：处理流 DAG（最核心的差异）

melobot 使用有向无环图（DAG）结构组织事件处理，这是与 NoneBot/AstrBot 最根本的架构差异。

### NoneBot 的模式（线性）

```
事件 → 规则检查 → 处理函数（中间件栈）
```

每个 `matcher` 内部是单一处理函数，最多通过中间件形成线性管道。

### melobot 的模式（DAG 图）

```python
from melobot.handle import Flow

# 每个位置参数是一条路径，路径中的列表表示同层的多个结点
# 结构由 references/melobot/src/melobot/handle/graph.py 的 DAGMapping 展开
flow = Flow(
    "complex-flow",
    [[n1, n2], n3, n4, [n5, n6], n7],
)
```

处理流对象内部维护一个真实的 DAG 数据结构（`DAGMapping`），按深度优先方式运行后继结点，支持分叉合并、结点复用。

这带来的能力：

| 能力 | NoneBot | melobot |
|------|---------|---------|
| 结点复用（同一逻辑段被多条路径共享） | 否 | 是 |
| 处理分叉与合并 | 需手动 if-else | 原生支持 |
| 基于类型注解的结点选择性执行 | 否 | 是 |
| 子流嵌套调用 | 否 | `flow_to()` |
| 处理流运行期反射 | 否 | `FlowRecord`（需 `Flow.enable_record()` 开启） |

---

## 二、处理流控制方法（精细管控执行流程）

melobot 提供了一整套流控制方法（来自 `references/melobot/src/melobot/handle/base.py`）：

```python
from melobot.handle import block, bypass, flow_to, nextn, node, rewind, stop


@node
async def example_node() -> None:
    await stop()     # 立即终止整个处理流（可以在多层函数嵌套内调用）
    await block()    # 阻断事件向更低优先级传播（不影响同级）
    await bypass()   # 跳过当前结点剩余步骤，进入下一结点
    await rewind()   # 重新执行当前结点（与会话搭配实现交互循环）

    with my_context:
        await nextn()  # 控制后继结点的运行时机，使其运行在自定义上下文环境中

    # 进入另一个处理流。关键字参数会写入子流的 FlowStore
    await flow_to(sub_flow, a=1, b=["2"])
    # 或者与子流共享当前流存储（此时关键字参数无效）
    await flow_to(sub_flow, True)
```

`flow_to(flow, share_store=False, /, **init_args)` 的前两个参数是仅位置参数；不共享存储时，`init_args` 成为子流 `FlowStore` 的初始内容。不能用 `flow_to` 进入自身所在的处理流。

NoneBot 中只能通过 `matcher.stop()` / `raise IgnoredException` 等有限手段控制流程，也没有 DAG 遍历可控制。

---

## 三、依赖注入（DI）系统的深度

melobot 的 DI 系统（`references/melobot/src/melobot/di.py`）：

### 3.1 自动依赖项（类型注解即依赖）

```python
# melobot：只需写类型注解
@on_message()
async def handler(event: MessageEvent, bot: Bot, adapter: Adapter, store: FlowStore) -> None: ...

# NoneBot：需要显式 Depends()
async def handler(event: MessageEvent = EventMessage(), bot: Bot = Depends(get_bot)): ...
```

可按注解自动注入的类型：事件、`Bot`、适配器、`GenericLogger`、`FlowStore`、`tuple[FlowRecord, ...]`、`Session`、`SessionStore`、`Rule`、解析参数（`AbstractParseArgs` 子类）。

### 3.2 DI 的区分调用（无 isinstance 的类型收窄）

```python
@on_message()
async def handler1(ev: GroupMessageEvent) -> None: ...  # 只有群聊消息触发
@on_message()
async def handler2(ev: PrivateMessageEvent) -> None: ...  # 只有私聊消息触发
```

这是 DAG 结点的选择性执行机制：注入时若真实类型与注解不匹配，框架抛出内部信号 `DependNotMatched`，该结点被视为未通过，不执行后继结点，无需任何 `isinstance` 判断。

### 3.3 高级 DI 特性

```python
from typing import Annotated

from melobot.di import Depends, inject_deps


# 递归依赖、子获取器、基于依赖项的依赖
@inject_deps
def f(
    a: Annotated[float, Depends(lambda: 3.14)],
    b: Annotated[int, Depends(dep_a, sub_getter=lambda x: int(x))],  # 子获取器
    c=(_d := Depends(get_val)),
    d=Depends(_d, sub_getter=lambda x: str(x)),  # 基于已有依赖项的依赖
) -> None: ...
```

`Depends` 默认 `recursive=True`，此时 `dep` 与 `sub_getter` 本身也会被注入依赖，因此必须是可注入的可调用对象。内建函数（如 `str`、`int`）不支持依赖注入，直接写 `sub_getter=str` 会在初始化时抛出 `DependInitError`，需要包一层 lambda，或者传 `recursive=False`。

`Exclude`、`Reflect`、`MatchEvent` 三种注解元数据各有一个等价的简略函数（均可从 `melobot` 顶级命名空间导入）：

```python
from melobot import exclude, match_event, ref

# 以下每组两种写法等价
arg: Annotated[A, Exclude(types=[B, C])]
arg: A = exclude(B, C)

arg: Annotated[Event, Reflect()]
arg: Event = ref()

arg: Annotated[ObAdapter, MatchEvent()]
arg: ObAdapter = match_event()

# 参数没有类型注解时（例如 lambda），需要显式给出基础类型
arg = ref(Event)
```

简略函数在参数无注解、又没有传 `base_type` 时，会在注入初始化阶段抛出 `DependResolveFailed`。

从流存储、会话存储取值的依赖项支持类型校验和默认值：

```python
from melobot.handle import get_flow_arg
from melobot.session import get_session_arg


async def node_func(
    a: int = get_flow_arg("a", verify=True),           # 按注解校验类型
    b=get_flow_arg("b", verify=True, type=list[str]),  # 无注解时用 type 参数
    c: str = get_session_arg("c", default="hi"),       # 取值失败时返回默认值
) -> None: ...
```

`verify=True` 时默认值同样参与类型校验，校验失败抛出 `DependNotMatched`。

### 3.4 反射式依赖注入（会话场景专用）

```python
from melobot.adapter import TextEvent
from melobot.di import ref
from melobot.handle import on_text
from melobot.session import suspend


@on_text(legacy_session=True)
async def handler(event: TextEvent = ref()) -> None:
    # event 在每次 suspend() 恢复后自动映射到最新事件，无需重新获取
    city = event.text
    await suspend()
    days = event.text  # 自动是下一条消息的内容
```

`ref()` 等价于 `Annotated[TextEvent, Reflect()]`。反射对象不允许访问或修改以 `_` 开头的属性。

---

## 四、多协议多路 IO（真正的多协议并行）

来自 `references/melobot/docs/source/dive_in/source_adapter.md` 与 `bot.md`，这是 melobot 相对于 NoneBot 最独特的架构能力之一。

```python
from melobot import Bot
from melobot.protocols.console import ConsoleProtocol
from melobot.protocols.onebot.v11 import OneBotV11Protocol, WSClient

bot = Bot("multi-protocol-bot")

# 同一个 OneBot 协议栈绑定多路输入输出（多账号）
bot.add_protocol(OneBotV11Protocol(WSClient(url_a), WSClient(url_b)))

# 同时添加控制台协议（本地调试）
bot.add_protocol(ConsoleProtocol())

# 第三方协议同理，也可以分别绑定源与适配器
# bot.add_io(SomeSource(...))
# bot.add_adapter(SomeAdapter(...))
```

源和适配器必须在配置期绑定：首次调用 `load_plugin` 系列方法就会初始化 bot 核心组件，此后 `add_input` / `add_output` / `add_io` / `add_adapter` / `add_protocol` 都不能再调用。这些方法都返回 bot 本身，可以链式调用。

输出时默认使用产生该事件的输入源（若它也是该协议的输出源），否则使用该协议的全部输出源。需要手动选择输出源时，用顶级函数 `filter_out` 包一层上下文：

```python
from melobot import filter_out, send_text

with filter_out(lambda src: src.name == "account-a"):
    await send_text("只从 account-a 发出")
```

| 能力 | NoneBot | melobot |
|------|---------|---------|
| 多协议同时接入 | 同进程内协议独立隔离 | 同一 bot 实例多协议并行 |
| 同协议多账号 | 需要多个驱动 | 同一适配器绑定多个源 |
| 跨协议通用行为方法 | 否 | `send_text()` 等通用操作自动适配 |
| 通用内容实体 `TextContent` | 否 | 屏蔽协议差异的内容层 |

---

## 五、插件 IPC：无导入依赖的跨插件通信

来自 `references/melobot/src/melobot/plugin/ipc.py`：

```python
from melobot.exceptions import ShareObjectCallbackFailed
from melobot.plugin import AsyncShare, PluginPlanner

# 插件 A 声明共享对象（无需被插件 B 导入）
my_data = AsyncShare[int]("user_count")


@my_data
async def get_count() -> int:
    return _count  # 实时反射值


@my_data.setter
async def set_count(val: int) -> None:
    global _count
    if val < 0:
        # 校验失败时推荐抛出专属异常，便于与其他异常区分
        raise ShareObjectCallbackFailed(val)
    _count = val


# 共享对象需要注册到插件管理器，且必须在本插件目录内定义（不能重导出）
plugin_a = PluginPlanner("0.1.0", shares=[my_data])

# 插件 B 从 bot 获取共享对象（无 import 依赖）
share = bot.get_share("plugin_a", "user_count")
count = await share.get()
```

getter / setter 也可以在构造时绑定：`AsyncShare(name, reflector=..., callback=..., static=...)`，`SyncShare` 同理。

NoneBot 插件间通信通常只能通过直接 `import`（强耦合）或全局状态。melobot 的 IPC 机制：

- `AsyncShare` 的 `get()` / `set()` 内部经过 `RWContext` 读写锁，getter 与 setter 支持依赖注入；`SyncShare` 直接调用绑定的函数，没有加锁
- 无导入依赖（通过插件名 + 共享对象名访问）；常规调用更推荐 `mb pinit` 生成的带类型提示接口
- 支持静态共享（`static=True`，不能绑定 setter）和动态共享（带 setter）

---

## 六、多进程支持（melobot.mp）

来自 `references/melobot/src/melobot/mp.py`，这是 NoneBot/AstrBot 均不具备的能力：

```python
from melobot.mp import PBox, SpawnProcess, SpawnProcessPool

# 安全的多进程任务，自动处理 spawn 模式下的入口点和序列化问题
proc = SpawnProcess(entry="worker.py", target=cpu_bound_task, args=(PBox(my_func),))
proc.start()

# PBox：自定义 pickle 包装器，解决 spawn 模式下的级联加载问题
boxed = PBox(my_function, module="my_module", entry="my_module.py")
```

melobot 在导入 `melobot.mp` 时替换了 `multiprocessing.spawn` 的 `get_preparation_data`、`get_command_line`、`prepare` 三个函数，实现了：

- 自定义子进程入口点（`entry` 必须是可加载的文件，避免主脚本在子进程中重新执行）
- 子进程自动忽略 `SIGINT`、`SIGTERM`（Windows 上还有 `SIGBREAK`），由父进程全权管理
- `PBox` 在 pickle 时临时改写对象的 `__module__` / `__qualname__` 并在之后恢复，实现跨进程序列化任意可调用对象；类或实例的方法不支持，需要 pickle 整个类或实例

---

## 七、处理流组合式 API（控制反转风格）

```python
# __plugin__.py
test_flow = Flow("test-flow")  # 先声明空流


# flows/step0.py
@test_flow.start  # 标记起始结点
@node
async def step0(event: MessageEvent) -> None: ...


# flows/step1.py（另一个模块，无需知道全局结构）
@test_flow.after(step0)
@node
async def step1() -> None: ...


# flows/step2.py（又另一个模块）
@test_flow.merge(step1, other_node)  # 声明汇聚点
@node
async def final_step() -> None: ...
```

`Flow` 提供 `start` / `after` / `before` / `merge` / `fork` 五个结构装饰器，它们会校验参数是否为 `FlowNode`，否则抛出 `FlowError`。这是一种控制反转（IoC）风格的 API，不需要在一处集中定义所有结点和边，各模块可以独立声明自己对流结构的贡献。NoneBot 没有此类机制。

---

## 八、日志系统的可扩展性

```python
import loguru

from melobot import Bot
from melobot.log import LoguruPatch, logger_patch

# 将第三方日志器接入 melobot。修补原地进行，返回的仍是同一个对象
loguru_logger = loguru.logger
patched = logger_patch(loguru_logger, LoguruPatch(loguru_logger))
bot = Bot(logger=patched)
```

`melobot.log` 内置 `StandardPatch`（标准库 `logging`）、`LoguruPatch`、`StructlogPatch` 三种修补，也可以自行实现 `LazyLogMethod`。修补应在第三方日志器自身配置完成之后进行。

melobot 内置日志器 `Logger` 的普通日志输出到 stdout，ERROR 及以上输出到 stderr；可以在多线程中使用，`is_parallel=True` 的并行渲染只在主线程生效，其他线程的日志走同步渲染。

---

## 九、异常格式化（开发者体验）

melobot 内置了 `better-exceptions` + `rich` 的异常美化渲染（`references/melobot/src/melobot/_render.py`），导入 `melobot` 时即安装为 `sys.excepthook`：

- 默认隐藏框架内部栈帧，只显示用户代码
- 支持 Jupyter/IPython 环境（需要手动调用 `install_exc_hook()`）
- 通过环境变量 `MELOBOT_EXC_SHOW_INTERNAL` / `MELOBOT_EXC_FLIP` 控制格式化风格，设置 `MELOBOT_EXC_FMT_FALLBACK` 则不安装钩子
- 跨 Python 3.10 至 3.14 版本兼容同一套 traceback 格式

---

## 十、3.5 新增与变更要点

以下内容按 melobot 3.5.0 的 changelog（`references/melobot/docs/source/update-log.md`）与源码整理，使用者需要注意：

- 生命周期：`BotLifeSpan` 只有 `STARTED`、`RESTARTED`、`CLOSE`、`STOPPED` 四个阶段，对应 `on_started` / `on_restarted` / `on_close` / `on_stopped`。插件生命周期只有 `PluginLifeSpan.READY`，对应 `PluginPlanner.on_ready`。`RESTARTED` 与 `STARTED` 都在所有适配器和源启动后触发，重启时 `RESTARTED` 先于 `STARTED`。
- 插件就绪回调：bot 启动时，在启动适配器之前为每个插件触发 `READY`。hook 以任务形式调度（不等待其完成），每个 hook 任务结束时把该插件的 `init_flows` 加入分发器；插件没有 `on_ready` hook 时立即加入。运行期加载的插件同样走这一流程。因此一个插件注册多个 `on_ready` hook 时，其处理流会被重复加入分发器（`Dispatcher.add` 不去重），一个插件只注册一个 `on_ready` 比较稳妥。
- 插件初始化参数：`bot.load_plugin(plugin, load_depth=1, /, **init_args)`，其中 `load_depth` 是仅位置参数；`load_plugins` / `load_plugins_dir` / `load_plugins_dirs` 用 `init_args` 参数按位置提供参数字典（不需要时用 `{}` 占位）。参数在 `on_ready` 回调中按参数名注入，回调里的其他参数仍按类型注解注入。接收初始化参数时建议把它们声明为仅关键字参数（写在 `*` 之后）：3.5.0 的注入实现会把带默认值的普通参数按位置补齐，若它前面有靠初始化参数提供的无默认值参数，默认值会错位到前面的参数上，调用时报 `DependResolveFailed`（got multiple values for argument）。官方文档里 `b: int, a: list[int], arg1: str = "hi"` 这种写法即受影响，改成 `*, b: int, a: list[int], arg1: str = "hi"` 可以正常工作。插件目录下可以写 `__pargs__.py`（内含名为 `Args` 的 `TypedDict`），让 `mb pinit` 生成带类型提示的参数定义。
- 动态导入的命名空间冲突检查：插件按 `load_depth` 拼出模块名导入，若同名模块已经从另一个目录导入过，会抛出 `ImportNameConflict`，提示调整导入深度或父目录名称。
- `Flow` 没有 `add` 方法，标记起始结点使用 `Flow.start`。
- `filter_out` 是从 `melobot.adapter`（也可从 `melobot` 顶级）导入的独立函数，不是适配器的方法。
- `AsyncShare` / `SyncShare` 构造参数名为 `callback`；共享对象回调失败的专属异常为 `melobot.exceptions.ShareObjectCallbackFailed`。
- DI 解析失败（不可恢复）的异常为 `DependResolveFailed`；动态导入异常基类为 `DynImportError`，其子类有 `ImportNameConflict`、`ImportSpecEmpty`。
- 顶级命名空间 `melobot` 可直接导入 `TextEvent`、`filter_out`、`lazy_action`、`exclude`、`ref`、`match_event`。

---

## 十一、总结对比

| 特性 | melobot | NoneBot v2 | AstrBot |
|------|---------|------------|---------|
| 处理流架构 | DAG 图（可自由搭建） | 线性中间件 | 线性处理 |
| 流控制方法 | stop/block/bypass/rewind/nextn/flow_to | 有限 | 无 |
| 依赖注入 | 深度 DI（自动、递归、反射、子获取器、类型校验） | 基础 DI | 无 |
| 多协议并行 | 同一 bot 多协议同时运行 | 协议隔离 | 多平台适配 |
| 同协议多账号 | 同 bot 多路 IO | 需多进程 | 部分支持 |
| 跨插件通信 | AsyncShare/SyncShare（IPC） | 直接导入 | 无 |
| 插件无序加载 | 是 | 否（依赖顺序） | 无 |
| 运行期动态加载插件 | 是 | 有限支持 | 无 |
| 会话机制 | suspend() + 自定义规则 | 有（相对简单） | 有（AI 对话上下文） |
| 多进程工具 | SpawnProcess + PBox | 无 | 无 |
| 日志框架兼容 | 任意框架（logger_patch） | 仅 logging | 仅 logging |
| 组合式流 API | IoC 风格 | 否 | 否 |
| 流运行期反射 | FlowRecord + FlowStore | 否 | 否 |
| 关注领域 | 通用 bot 框架 | 通用（偏 QQ） | AI 对话优先 |

一句话总结：melobot 的核心优势是基于 DAG 的处理流系统与深度依赖注入，使得复杂事件处理逻辑的组织、复用和扩展比传统线性框架灵活得多。多协议多路 IO 并行、IPC 插件通信机制和内置多进程工具链是它在架构层面区别于其他框架的另外三处特点。代价是学习曲线相对较陡，文档中 "dive in" 部分的内容比 NoneBot 的教程要深得多。

---

*另见：[melobot 预处理机制详解（checker/matcher/parser）](./preprocess-mechanism.md)*
