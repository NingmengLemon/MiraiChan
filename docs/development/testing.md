# 测试

## 运行

```sh
uv run pytest
```

在仓库根运行。根 `pyproject.toml` 的 `[tool.pytest.ini_options]` 用 `testpaths` 显式列出测试目录,
并通过 `norecursedirs` 排除 `references/` 等外部目录; 新增测试目录时要加进 `testpaths`。

## 放置

- 共享库 (`packages/shared/<pkg>/`): 测试放在包自己的 `tests/` 下。
- 插件 (`packages/plugins/<plugin>/`): 测试放在仓库根 `tests/plugins/` 下, 不能放在插件目录里。

插件不能就地放测试, 原因是 melobot 为插件生成的 `__init__.py` 定义了模块级 `__getattr__`,
其内部通过 `BotCtx().get()` 查询跨插件共享对象。pytest 收集包内测试时会导入插件的 `__init__.py`
并 `getattr(mod, "pytest_plugins")`, 此时没有 bot 实例, 抛出 `BotError: 此时未初始化 bot 实例`。

根目录下的插件测试通过把 `packages/plugins` 插入 `sys.path` 来导入插件子模块
(如 `mbplugin_deeeer.migration`), 并且只能导入不依赖 bot 上下文的模块: `__plugin__.py` 在模块级
调用了 `get_bot()`, 不能在测试里导入。

一个插件有多个测试文件时放进子目录 (如 `tests/plugins/quote/`), 用该目录的 `conftest.py` 统一设置 `sys.path`。

## 数据

测试不得读写 `data/` 下的真实数据。用 `tmp_path` 并通过
`lemony_storage_helper.database.sqlite.set_relative_path_base(tmp_path)` 重定向存储根目录。

## 端到端冒烟

`tools/fake_onebot_server.py` 是一个最小的 OneBot v11 正向 ws 服务端: 按 JSON 场景推送事件、
为 `get_msg` 返回预置消息, 并把 bot 发出的全部 action 记录为 JSON Lines。配合环境变量
`MIRAICHAN_PROJECT_ROOT` 把 bot 的项目根 (`config.json`、`configs/`、`data/`) 指到一个临时目录,
即可在不碰真实数据与真实账号的前提下跑完整的 bot:

1. 在临时目录放 `miracle_entrance.py`、`config.json` (websocket 指向假服务端, `plugins` 写插件目录的绝对路径)、
   需要的 `configs/` (例如 `lemony_checkers/global.json` 里的 owner) 与 `data/fonts/`;
2. 先启动假服务端, 再以 `MIRAICHAN_PROJECT_ROOT=<临时目录>` 启动 bot;
3. 假服务端在 bot 空闲一段时间后退出, 之后检查记录的 action 与临时目录下产生的数据。

场景里的 QQ 号、群号、消息内容一律用构造值。

现成的演练脚本把上面的步骤封装好了, 退出码 0 表示全部检查通过:

- `tools/rehearse_e2e.py`: 上线插件组合 (recorder、deeeer、quote 等) 的关键路径
- `tools/rehearse_alerts.py`: 预警插件, 额外启动 `tools/mock_wolfx_server.py` 模拟 Wolfx,
  经它的 `POST /_mock/push` 触发推送
