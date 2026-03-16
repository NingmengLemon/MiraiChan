# 代码评审与重构建议

> 覆盖范围：`packages/shared/`（全部）、`packages/plugins/`（除 `_to_be_migrated`）、`packages/miraichan/`  
> 当前状态：快速迭代期，破坏性重构建议已标注 ⚠️

---

## 目录

1. [全局性设计问题](#1-全局性设计问题)
2. [lemony_checkers](#2-lemony_checkers)
3. [lemony_settings](#3-lemony_settings)
4. [lemony_storage_helper](#4-lemony_storage_helper)
5. [lemony_images](#5-lemony_images)
6. [lemony_utils_legacy](#6-lemony_utils_legacy)
7. [lemony_network](#7-lemony_network)
8. [lemony_utils（新包）](#8-lemony_utils新包)
9. [miraichan 核心](#9-miraichan-核心)
10. [插件层](#10-插件层)
11. [优先级总结](#11-优先级总结)

---

## 1. 全局性设计问题

### 1.1 ⚠️ 用 `ContextVar` 存储全局单例是反模式

**涉及文件：**

- [`packages/shared/lemony_settings/src/lemony_settings/manager.py`](../packages/shared/lemony_settings/src/lemony_settings/manager.py:117)
- [`packages/shared/lemony_checkers/src/lemony_checkers/factory.py`](../packages/shared/lemony_checkers/src/lemony_checkers/factory.py:254)
- [`packages/shared/lemony_images/src/lemony_images/font.py`](../packages/shared/lemony_images/src/lemony_images/font.py:38)

**问题：**

`ContextVar` 是为"协程上下文隔离"设计的（比如 HTTP 服务器里每个请求有独立的用户上下文）。对于进程级别的单例，用模块变量就够了。

当前代码的隐患：`asyncio.create_task(...)` 会**复制**当前协程上下文到新 Task 中。这意味着：

1. 在主上下文中调用 `init_settings_manager()` 后，后续通过 `create_task` 创建的 Task 能读到正确值（因为是复制的）
2. 但如果 Task 内部修改了 ContextVar（理论上不会，但容易混淆）主上下文看不到变化
3. 最关键的问题：`_reset_for_testing()` 只重置了当前上下文的值，不影响其他已运行的 Task 的副本，这让测试隔离变得复杂

**建议：** 直接用模块级变量：

```python
# 替换
_manager_instance: ContextVar[SettingsManager | None] = ContextVar(...)

# 为
_manager_instance: SettingsManager | None = None
```

`_reset_for_testing()` 依然可以工作，只是直接赋值 `None` 即可。

---

### 1.2 同步 IO 操作阻塞异步事件循环

**涉及文件：**

- [`packages/shared/lemony_settings/src/lemony_settings/core.py`](../packages/shared/lemony_settings/src/lemony_settings/core.py:105) — `save()` 和 `load()` 里有同步 `FileLock` + 文件 IO
- [`packages/plugins/mbplugin_checker_manager/__plugin__.py`](../packages/plugins/mbplugin_checker_manager/__plugin__.py:206) — 在 async handler 里用同步 `with EditContext(...):`

**问题：** `FileLock(lock_file, timeout=10)` 的 `with lock:` 是阻塞调用（最多阻塞10秒），在 melobot 的 async handler 里调用会直接挂起整个事件循环。

**建议（不破坏接口）：** 在内部用 `asyncio.to_thread` 包裹文件操作：

```python
async def save_async(self) -> None:
    await asyncio.to_thread(self.save)

async def load_async(self) -> None:
    await asyncio.to_thread(self.load)
```

并在 handler 里调用 `async with EditContext(...)` 的异步版本，或在 `EditContext.__aexit__` 里用 `asyncio.to_thread` 执行保存。

---

## 2. lemony_checkers

### 2.1 ⚠️ `FailCallbackMixin` + `Checker` 多继承初始化不完整

**文件：** [`packages/shared/lemony_checkers/src/lemony_checkers/checkers.py`](../packages/shared/lemony_checkers/src/lemony_checkers/checkers.py:247)

**问题：** `LemonyChecker(Checker[MessageEvent], FailCallbackMixin)` 中：

```python
def __init__(self, ..., fail_cb, factory):
    FailCallbackMixin.__init__(self, fail_cb=fail_cb)  # ← 调用了
    # Checker.__init__ 没有调用！
```

`Checker.__init__` 设置了 `self.fail_cb = to_async(fail_cb)`，这个属性被 `WrappedChecker.check()` 使用。虽然 `LemonyChecker` 自己的 `check()` 方法用 `self._fire_fail_cb(event)` 绕过了这个问题，但：

1. 如果用 `LemonyChecker() | some_other_checker` 生成 `WrappedChecker`，`WrappedChecker` 的 fail_cb 是 `None`（因为 `LemonyChecker` 从 Checker 继承的 `self.fail_cb` 未被初始化）
2. 如果某个地方依赖 `checker.fail_cb` 属性（比如 `set_fail_cb` 方法），行为未定义

**修复方案 A（简单修复）：** 在 `__init__` 里也调用 `Checker.__init__`：

```python
Checker.__init__(self, fail_cb=None)  # 把 Checker 的 fail_cb 置 None，因为我们用自己的
FailCallbackMixin.__init__(self, fail_cb=fail_cb)
```

**修复方案 B（重构，推荐）：** 不再让 `LemonyChecker` 继承 `Checker`，而是让它实现 melobot `Checker` 协议（鸭子类型），或者合并 `FailCallbackMixin` 进 `Checker` 子类：

```python
class LemonyChecker(Checker[MessageEvent]):
    def __init__(self, ..., fail_cb: FailCallback | None, ...):
        super().__init__()  # Checker.__init__ 不传 fail_cb
        self._fail_cb = fail_cb  # 自己管理 fail_cb，但类型不同
```

---

### 2.2 `FailCallback` 签名与 melobot 内置检查器不兼容

**文件：** [`packages/shared/lemony_checkers/src/lemony_checkers/checkers.py`](../packages/shared/lemony_checkers/src/lemony_checkers/checkers.py:37)

```python
type FailCallback = Callable[[MessageEvent], Awaitable[Any]]  # 接收 event
# vs melobot 内置
self.fail_cb: Callable[[], None]  # 无参
```

这两种 `fail_cb` 无法互换使用。如果将 `LemonyChecker` 与 melobot 内置 checker 用 `|` 组合成 `WrappedChecker`，`WrappedChecker.fail_cb` 无法统一调用。

**这个设计目前没有实际 bug**（因为 `LemonyChecker.check()` 内部直接调用 `_fire_fail_cb(event)`，绕过了 `WrappedChecker` 的 fail_cb 机制）。但需要注意组合时的语义。

---

### 2.3 `_CheckerFactoryWrapper.__call__` 的代理链过长

**文件：** [`packages/shared/lemony_checkers/src/lemony_checkers/factory.py`](../packages/shared/lemony_checkers/src/lemony_checkers/factory.py:324)

代码里也有注释："感觉这样一层一层的 proxy 还是挺麻烦的，以后可能需要重构一下设计"。

调用链：`_CheckerFactoryWrapper.__call__` → `LemonyCheckerFactory.new_checker` → `LemonyChecker.__init__`

**建议：** 这三层的参数几乎完全相同，可以合并。`_CheckerFactoryWrapper` 实际上只是一个参数预填充的包装，可以简化为一个带 `partial` 的工厂函数，或直接在 `LemonyCheckerFactory` 上提供一个 `get_wrapper()` 方法返回一个预填充的 `partial(new_checker, ...)`.

---

### 2.4 `EditContext` 中的同步保存（见 1.2）

---

## 3. lemony_settings

### 3.1 `SettingsManager._post_init()` 中有永远不会触发的检查

**文件：** [`packages/shared/lemony_settings/src/lemony_settings/manager.py`](../packages/shared/lemony_settings/src/lemony_settings/manager.py:43)

```python
def _post_init(self):
    if self._global_settings is not None:  # 在 __init__ 里 _global_settings=None，这里永远是 None
        raise RuntimeError("SettingsManager has already been initialized.")
```

这个检查永远不会 `True`，因为 `__init__` 里 `self._global_settings = None`，然后立即调用 `_post_init()`。注释说是为了"未来多实例化准备"，但当前逻辑是死代码。

---

### 3.2 TOML 支持已知有 `None` 字段问题

**文件：** [`packages/shared/lemony_settings/src/lemony_settings/readwriter.py`](../packages/shared/lemony_settings/src/lemony_settings/readwriter.py:42)

`TomlReadWriter.write` 使用 `model_dump(exclude_none=True)`，导致 `None` 值字段写入时被排除，读回时 Pydantic 会使用字段默认值（如果有）。但如果用户明确设置了一个字段为 `None`（比如 `owner: None`），重新加载后仍然是 `None`（因为 default 是 `None`）。这在当前场景下可能没问题，但需要知道这个 TOML 限制。

---

### 3.3 `GlobalSettings` 分层设计过于复杂

**文件：** [`packages/shared/lemony_settings/src/lemony_settings/models.py`](../packages/shared/lemony_settings/src/lemony_settings/models.py)

`GlobalSettings` 嵌套了 `PersistentGlobalSettings`，但目前 `PersistentGlobalSettings` 只有一个 `auto_reload: bool` 字段，且 `auto_reload` 功能（自动重载）并未实现（`watcher.py` 文件只有37字节，几乎是空的）。

**建议：** 在 `auto_reload` 未实现之前，直接把 `auto_reload` 字段扁平化放到 `GlobalSettings` 里，去掉 `PersistentGlobalSettings` 这一层。

---

## 4. lemony_storage_helper

### 4.1 `to_async` 装饰器每次调用都创建新 Session 和事务

**文件：** [`packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/generic.py`](../packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/generic.py:184)

```python
def to_async(self, func):
    @functools.wraps(func)
    async def wrapped(*args, **kwargs):
        return await self.run_sync(func, *args, **kwargs)  # 每次开新 Session + 事务
    return wrapped
```

`deeeer` 插件中的 `query` 和 `record` 都用了 `@deerdbcore.to_async`，它们是独立的数据库事务。目前这是正确的，因为两个操作是独立的。

**潜在问题：** 如果未来需要"query + conditional record"在同一事务里，当前 API 无法支持。但这不是现在的问题，只是设计限制需要知道。

---

### 4.2 ⚠️ `deerdbcore` 模块级实例化依赖外部初始化顺序

**文件：** [`packages/plugins/mbplugin_deeeer/core.py`](../packages/plugins/mbplugin_deeeer/core.py:31)

```python
DBPPATH = "record/deers.db"  # 相对路径
deerdbcore = SqliteDatabaseHelper(DBPPATH, metadata=deerdb_registry.metadata)
# ↑ 在模块导入时执行
```

`SqliteDatabaseHelper.__init__` 里会查询 `_upper_layer_managed_relative_path_base.get()`。如果在 `miraichan/bot.py` 的 `init_modules()` 调用 `set_relative_path_base(...)` **之前**导入了 `deeeer`，就会触发 `ValueError: relative_path_base is required`。

从代码流程看：`miraichan/bot.py` → `init_modules(cfg)` → `set_relative_path_base(...)` → 之后再 `bot.load_plugins(plugins)` 加载插件，所以目前顺序是对的。但这个隐式依赖很脆弱。

**建议：** 在 `deeeer/__plugin__.py` 的 `@bot.on_started` 钩子里延迟实例化 `deerdbcore`，不要在模块级实例化：

```python
deerdbcore: SqliteDatabaseHelper | None = None

@bot.on_started
async def _():
    global deerdbcore
    deerdbcore = SqliteDatabaseHelper(DBPPATH, metadata=deerdb_registry.metadata)
    await deerdbcore.startup(...)
```

---

### 4.3 `GenericAsyncAttrs` 泛型和 `queryable()` 工具函数只用于类型检查

**文件：** [`packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/utils.py`](../packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/utils.py:276)

`GenericAsyncAttrs[T]` 的 `awaitable_attrs: T` 只在 `TYPE_CHECKING` 下有效，运行时不存在。`queryable(o)` 只是 `cast(QueryableAttribute, o)` 的别名。这些纯粹是类型注解辅助，本质上没有运行时行为。这是合理的做法，只是需要知道它们的用途。

---

## 5. lemony_images

### 5.1 `FontCache.usec` 是无意义的上下文管理器

**文件：** [`packages/shared/lemony_images/src/lemony_images/font.py`](../packages/shared/lemony_images/src/lemony_images/font.py:29)

```python
@contextmanager
def usec(self, size: int):
    yield self.use(size=size)
```

字体对象（`ImageFont.FreeTypeFont`）不需要清理，`contextmanager` 在这里什么都不做。这个方法是多余的——`calc_font_size` 里用 `with fontcache.usec(size=fsize) as font:` 的唯一目的是限制变量作用域，但 Python 的 `with` 语句并不能限制变量作用域（`font` 变量在 `with` 块外仍然可见）。

**建议：** 直接用 `font = fontcache.use(fsize)` 即可，删掉 `usec`。

---

### 5.2 `calc_font_size` 里 `wrap_text_by_width` 被调用两次

**文件：** [`packages/shared/lemony_images/src/lemony_images/layout.py`](../packages/shared/lemony_images/src/lemony_images/layout.py:60)

```python
def calc_font_size(...):
    while fsize > min_font_size:
        with fontcache.usec(size=fsize) as font:
            wrapped_lines = wrap_text_by_width(text, box_width, font)  # 第一次 wrap
            ...
    return fsize, "\n".join(wrap_text_by_width(text, box_width, fontcache.use(fsize)))  # 第二次 wrap
```

退出循环后重复调用了一次 `wrap_text_by_width`。直接用 `"\n".join(wrapped_lines)` 即可（但注意 `fsize` 最后一次循环后 `wrapped_lines` 是正确的），或在 `break` 时保存结果。

---

### 5.3 `draw_multiline_text_auto` 的 `kwargs.pop` 副作用

**文件：** [`packages/shared/lemony_images/src/lemony_images/layout.py`](../packages/shared/lemony_images/src/lemony_images/layout.py:145)

函数内部修改了传入的 `kwargs` dict（`kwargs.pop(kw, None)`）。如果调用者的 `**kwargs` 来自一个外部 dict，这会修改调用者的数据。应该用 `kwargs = {k: v for k, v in kwargs.items() if k not in (...)}` 替代。

---

## 6. lemony_utils_legacy

### 6.1 ⚠️ `AvatarCache` 单例 + 参数 + 模块级实例化的三重问题

**文件：** [`packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/botutils.py`](../packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/botutils.py:72)

问题 1：`@singleton` 装饰类后，所有参数只在第一次实例化时有效，之后忽略，但文档没有说明这一点。代码注释 `# TODO: 那我问你这个单例怎么传参数` 说明作者也意识到了这个问题。

问题 2：`cached_avatar_source = AvatarCache()` 在模块导入时实例化，此时 `auto_close=True` 意味着需要 `get_bot()`，但 `get_bot()` 在 `get()` 方法里才被调用（懒加载），所以这个问题暂时没爆，但设计上很脆弱。

问题 3：`_update_times` 内存字典在 bot 重启后会丢失，导致每次重启都重新下载所有头像（注释 `# TODO: use mtime instead of a separate dict` 已提到）。

**建议：** 用 `os.path.getmtime(path)` 替代内存字典来判断缓存有效性，同时用 `asyncio.to_thread(os.path.getmtime, path)` 避免阻塞。

---

### 6.2 硬编码相对路径 `"data/avatars"`

**文件：** [`packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/botutils.py`](../packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/botutils.py:74)

同样的问题在 `deeeer/core.py:128` 也有（`"data/no_data.png"`）。这两处都依赖 `os.chdir()` 到项目根目录（在 `bot.py` 里调用），这是一个隐式的全局状态依赖。

**建议（分两步）：**

1. 短期：保持 `os.chdir` 的做法，但在 `AvatarCache` 里用 `get_project_root()` 构建绝对路径
2. 长期：引入统一的资源路径管理，就像 `lemony_storage_helper` 里的 `set_relative_path_base` 模式

---

### 6.3 `ThreadWithReturn` 的 `run()` 里重复设置了已有属性

**文件：** [`packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/asyncutils.py`](../packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/asyncutils.py:17)

`threading.Thread` 父类已经在 `__init__` 里保存了 `_target`、`_args`、`_kwargs`，子类里重新赋值这些私有属性是多余的（实际上这些名字可能会随 Python 版本变化）。`run()` 里 `del self._target, self._args, self._kwargs` 也会与父类产生冲突（父类的 `run()` 最后也会 `del`，可能报 `AttributeError`）。

不过这个类的实际使用场景可能不多，先标记即可。

---

### 6.4 `InteractiveProcess.drain_output` 直接 `print` 而非使用日志器

**文件：** [`packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/asyncutils.py`](../packages/shared/lemony_utils_legacy/src/lemony_utils_legacy/asyncutils.py:82)

调试用的 `print("drained:", line.strip())` 应该用 logger。

---

## 7. lemony_network

### 7.1 `async_http` 内部 `raise_for_status()` 不应该双重调用

**文件：** [`packages/shared/lemony_network/src/lemony_network/request.py`](../packages/shared/lemony_network/src/lemony_network/request.py:44)

`async_http` 已经在内部调用了 `response.raise_for_status()`，而且上层代码（如 `AvatarCache.get_from_remote`）在用 `async with async_http(...)` 时又单独调用了 `resp.raise_for_status()`，存在重复调用（虽然不是 bug，因为 raise_for_status 是幂等的）。

更重要的问题：`raise_for_status()` 在 `yield response` **之前**调用，这意味着如果状态码不正常，generator 不会被正确清理（aiohttp 的 context manager 可能已经处理了这个，但值得注意）。

---

### 7.2 `http_headers` 硬编码了 Windows Chrome 的 UA

**文件：** [`packages/shared/lemony_network/src/lemony_network/request.py`](../packages/shared/lemony_network/src/lemony_network/request.py:18)

UA 里写死了 `Windows NT 10.0`，当 bot 运行在 Linux 上时会有些奇怪。但这是已知的伪装行为，不影响功能。

---

## 8. lemony_utils（新包）

### 8.1 `singleton_holder.py` 是空文件

**文件：** [`packages/shared/lemony_utils/src/lemony_utils/singleton_holder.py`](../packages/shared/lemony_utils/src/lemony_utils/singleton_holder.py)

文件里只有注释，没有任何实际代码：

```python
# 这个包主要用于管理以下包的单例状态:
# - lemony_storage_helper.database.sqlite # 的上层 relative_base_path
# - lemony_settings # 的 manager
# - lemony_checkers # 的 factory
# - lemony_images.font # 的 default_font_cache
```

如果要真正集中管理这些单例，可以在这里提供统一的初始化入口。但目前 `miraichan/bot.py` 已经在 `init_modules()` 里按序调用了各包的初始化函数，相当于手动实现了这个职责。

**建议：** 如果要保留 `singleton_holder` 包，可以把 `init_modules` 的逻辑提取到这里，提供一个 `init_all(config)` 函数，让 `bot.py` 调用。

---

## 9. miraichan 核心

### 9.1 `loader.py` 的 fallback 路径依赖文件系统结构

**文件：** [`packages/miraichan/src/miraichan/loader.py`](../packages/miraichan/src/miraichan/loader.py:50)

```python
packages_dir = Path(__file__).parent.parent.parent.parent.resolve()
# __file__ = packages/miraichan/src/miraichan/loader.py
# parent×4 = packages/
candidate_path = packages_dir / "plugins" / plugin_name
```

这个 fallback 是"内置插件"（`packages/plugins/` 下的插件）的加载机制。如果 `miraichan` 包被安装到 site-packages，这个路径计算就会出错。

当前项目结构下这不是问题（使用 `uv` 的 workspace 模式，所有包都以 editable 方式安装），但值得注意。

---

### 9.2 `validation_patches/ob11.py` 修补了 melobot 内部行为

**文件：** [`packages/miraichan/src/miraichan/validation_patches/ob11.py`](../packages/miraichan/src/miraichan/validation_patches/ob11.py)

`adapter.when_validate_error(type_)(patch)` 使用了 melobot 的 `Adapter.when_validate_error` 接口——这是合法的 melobot 公开 API（文档中有提及），不是 hack。

补丁本身的设计（用 `mark_patch` 装饰器注册，然后 `patch_all` 批量应用）是合理的。

---

### 9.3 `utils.py` 里的 `custom_melobot_logo` hack 警告

**文件：** [`packages/miraichan/src/miraichan/utils.py`](../packages/miraichan/src/miraichan/utils.py:35)

```python
from melobot._meta import MetaInfoMeta
setattr(MetaInfoMeta, "logo", new_logo.strip())
```

注释已经说了"私有成员注意，后续随时可能被改掉"。这是对 melobot 内部元类的 hack，随 melobot 版本更新可能失效，但已经有 try/except 防护。

---

## 10. 插件层

### 10.1 ⚠️ `mbplugin_deeeer` 中配置加载两次

**文件：** [`packages/plugins/mbplugin_deeeer/__plugin__.py`](../packages/plugins/mbplugin_deeeer/__plugin__.py:41)

```python
cfgloader = require(model=CfgModel, identifier=PLUGIN_IDENTIFIER)  # auto_load=True，这里就加载了
# ...
@bot.on_started
async def _():
    cfgloader.load()  # 这里又加载了一次
    await asyncio.to_thread(post_init)
    await deerdbcore.startup(...)
```

`require()` 默认 `auto_load=True`，第一次调用时已经从文件加载了配置。`on_started` 里的 `cfgloader.load()` 是多余的（除非意图是"在 bot 完全启动后确保最新配置"，但 bot 启动期间没有人会修改配置文件）。

**建议：** 删除 `cfgloader.load()` 那一行，保持简洁。但要确认 `post_init()` 确实是在 `on_started` 里才执行（而不是在模块导入时），因为它依赖 `cfgloader.value`。

---

### 10.2 `mbplugin_deeeer` 的 `post_init` 修改全局变量

**文件：** [`packages/plugins/mbplugin_deeeer/__plugin__.py`](../packages/plugins/mbplugin_deeeer/__plugin__.py:62)

`post_init()` 使用 `global` 关键字修改多个模块级变量（`DEER_CHARS`, `DEER_JUDGE_REGEX` 等）。这些变量在 `post_init()` 调用前是未初始化的，如果 `post_init()` 未被调用就触发了 `deer` handler，会有 `NameError`。

**建议：** 把这些变量封装到一个 `dataclass` 或 dict 里，或者整个作为 `DeerPlugin` 类的属性，避免模块级全局变量。

---

### 10.3 `mbplugin_moelottery` 里 cd_table 没有持久化

**文件：** [`packages/plugins/mbplugin_moelottery/__plugin__.py`](../packages/plugins/mbplugin_moelottery/__plugin__.py:30)

```python
cd_table: dict[tuple[int, int], str] = {}  # 用于冷却
```

`cd_table` 是内存字典，bot 重启后重置。这意味着重启后冷却时间失效，用户可以重新抽签。这是已知的设计取舍（对于签到类功能，重启后允许重新抽可能是可以接受的），只是需要明确这一点。

---

### 10.4 `checker_command` 不使用 `LemonyChecker` 而是手动检查权限（正确做法）

**文件：** [`packages/plugins/mbplugin_checker_manager/__plugin__.py`](../packages/plugins/mbplugin_checker_manager/__plugin__.py:116)

```python
@on_command(".", " ", ["checker", "ck"])
async def checker_command(adapter: Adapter, event: MessageEvent, args: CmdArgs):
    if not _check_privilege(user_id):  # 在 handler 里手动检查，不用 checker= 参数
        await adapter.send_reply("无权使用此指令")
        return
```

这是**正确的做法**——避免了 checker 在守卫阶段（matcher 之前）触发 fail_cb 的问题（见 `docs/melobot_preprocess_mechanism.md`）。但其他插件（`deeeer`、`moelottery`）用的是 `checker_factory(...).check(event)` 在 handler 里调用，两种模式的区别在于：

- `checker_command`：无 fail_cb，只有拒绝回复（在 handler 里写 `await adapter.send_reply(...)`）
- `deeeer`/`moelottery`：`checker_factory(...).check(event)` 也在 handler 里调用，fail_cb 无操作（因为没设置）

这两种模式是一致的，都是正确的。

---

## 11. 优先级总结

### 🔴 需要修复的 Bug / 高风险问题

| # | 位置 | 问题 |
|---|------|------|
| 1 | `lemony_checkers/checkers.py` | `LemonyChecker` 未调用 `Checker.__init__`，基类 `fail_cb` 属性未初始化 |
| 2 | `lemony_settings/core.py` | `save()`/`load()` 同步 FileLock 阻塞异步事件循环 |
| 3 | `mbplugin_deeeer/core.py` | `deerdbcore` 模块级实例化依赖外部初始化顺序，隐式依赖很脆弱 |

### 🟡 值得重构的设计问题

| # | 位置 | 问题 |
|---|------|------|
| 4 | 多处 `ContextVar` 单例 | 用模块变量替代，语义更清晰 |
| 5 | `lemony_images/layout.py` | `calc_font_size` 里 `wrap_text_by_width` 被调用两次，性能浪费 |
| 6 | `lemony_images/font.py` | `usec` 是无用的上下文管理器，可以删除 |
| 7 | `lemony_utils_legacy/botutils.py` | `AvatarCache` 使用内存字典跟踪缓存时间，重启后失效 |
| 8 | `mbplugin_deeeer/__plugin__.py` | `cfgloader.load()` 在 `on_started` 里是多余的 |
| 9 | `mbplugin_deeeer/__plugin__.py` | `post_init()` 用 `global` 修改模块变量，建议封装 |
| 10 | `lemony_checkers/factory.py` | `_CheckerFactoryWrapper` 代理链过长，可以简化 |

### 🟢 低优先级 / TODO 确认

| # | 位置 | 问题 |
|---|------|------|
| 11 | `lemony_utils_legacy/botutils.py` | 硬编码相对路径 `"data/avatars"` |
| 12 | `mbplugin_deeeer/core.py` | 硬编码相对路径 `"data/no_data.png"` |
| 13 | `lemony_settings/models.py` | `PersistentGlobalSettings` 层级在 `auto_reload` 未实现前可简化 |
| 14 | `lemony_utils/singleton_holder.py` | 空文件，决定是否真正实现统一初始化入口 |
| 15 | `mbplugin_moelottery/__plugin__.py` | `cd_table` 内存字典在重启后重置，确认这是预期行为 |
