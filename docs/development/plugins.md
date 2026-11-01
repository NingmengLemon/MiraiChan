# 插件开发注意事项

## 命令参数里的 `.` 会被切开

melobot 的命令解析器按命令起始符切分参数, 参数里出现 `.` 会被当成下一条命令的起点,
`CmdArgs` 拿到的 token 已经被截断。表现是参数"少了一半"而且不报错。

实际踩到的例子: `.mq -5..5` 进到插件里是 `['-5']`, 区间正半段静默丢失, 用户看到的是
"区间 >0 的部分不生效"。

两种写法可以避开:

- `@on_start_match(".tts ")` 自己取消息原文, 再截掉前缀 (`mbplugin_quote` 的旧实现在
  `_to_be_migrated/VVTTS` 里就是这么做的);
- `@on_command(...)` 只用来匹配命令名, 参数从 `event.text` 里自己切,
  例如 `mbplugin_quote.request.chat_tokens()`: 去掉命令前缀, 按空白切分, 遇到下一个命令起始符就停。

带链接、小数、缩写、区间这类参数的命令都要注意这一点。纯粹的单词参数 (子命令、开关) 用
`CmdArgs` 没问题。

## 入口模块不要用 postponed annotations

`packages/plugins/*/__plugin__.py` 里写 `from __future__ import annotations` 会让 handler 的参数注解
变成字符串, melobot 用 beartype 解析签名时拿不到真正的类型, 插件在加载阶段直接失败:

```
beartype.roar.BeartypeDoorNonpepException: Type hint 'MessageEvent' currently unsupported
```

单元测试发现不了, 因为测试不会 import 入口模块 (那需要 bot 实例)。`tests/plugins/test_plugin_entries.py`
会静态检查所有入口模块, 不要在入口模块里加这一行; 其它模块用不用无所谓。

## 初始化与配置加载

默认用延迟初始化: `require(..., auto_load=False)`, 在 `on_ready` 里 `await cfgloader.load_async()`
建好运行期对象, handler 先看 `state.ready`:

```python
cfgloader = require(model=Settings, identifier=PLUGIN_IDENTIFIER, auto_load=False)


class _State:
    ready = False
    settings: Settings
    # 其它需要初始化的对象


state = _State()


@plugin.on_ready
async def _() -> None:
    try:
        await cfgloader.load_async()
        state.settings = cfgloader.value
        # 初始化数据库、线程池、资源等
        state.ready = True
    except Exception:
        logger.exception(f"{PLUGIN_IDENTIFIER} 初始化失败, 插件将不响应")


@plugin.use
@on_command(...)
async def handler(...) -> None:
    if not state.ready:
        return
    ...
```

例外: 命令名、别名或帮助文本必须由配置决定时, 只能在 import 时让 `require()` 自动加载
(provenance / rebootable / deeeer 属于这一类)。此时不要再手动调 `cfgloader.load()` 或
`load_async()`; 配置损坏会让插件在加载阶段失败, 这是该模式的已知代价。
`tests/plugins/test_plugin_entries.py` 会静态禁止入口模块里的同步 `cfgloader.load()`。
