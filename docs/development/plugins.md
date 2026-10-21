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
