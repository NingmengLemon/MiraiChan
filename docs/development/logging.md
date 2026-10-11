# 日志与 debug 开关

## 约定

插件、共享库都用标准库日志器:

```python
import logging

logger = logging.getLogger(__name__)
```

模块内不判断"当前是否 debug 模式", 只按语义选级别 (`debug` / `info` / ...)。是否输出由 logging 的层级决定。

## 机制

`miraichan.logging_bridge.install_logging_bridge` 在启动时把一个转发 handler 挂到 root logger 上,
所有标准 logging 记录 (包括 sqlalchemy、aiohttp 等第三方库) 都交给 melobot 全局日志器的 handler 输出,
格式与 melobot 自身日志一致。

- root 级别: `config.json` 的 `debug` 或命令行 `--debug` 为真时是 DEBUG, 否则 INFO。
- 子树级别: `config.json` 的 `log_levels` 按日志器名覆盖, 例如:

```json
{
    "log_levels": {
        "sqlalchemy.engine": "INFO",
        "mbplugin_recorder": "DEBUG",
        "aiohttp": "WARNING"
    }
}
```

`sqlalchemy.engine` 设为 INFO 即打开 SQL 日志, 不需要 `create_async_engine(echo=True)`。
`SqliteDatabaseHelper.startup` 的 `echo` 参数保留, 但插件不应传入。

## 不用 setLoggerClass(melobot.log.Logger) 的原因

melobot `Logger` 构造时固定 `level=DEBUG` 且自带 handler。若把它设为 logging 的默认日志器类,
每个 `getLogger(__name__)` 都是一个独立的 DEBUG 级日志器, `logger.level` 恒为 DEBUG,
级别无法从外部统一控制, 依赖它的判断 (例如据此决定 SQL echo) 也恒为真。

## 插件初始化参数

melobot 3.5 的 `load_plugins(..., init_args=...)` 可以给插件 `on_ready` 传参, 适合传插件私有、
与日志无关的配置。debug 开关不走这条路: 普通模块拿不到 init_args, 而日志级别已经由 logging 层级统一表达。
