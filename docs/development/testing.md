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

## 数据

测试不得读写 `data/` 下的真实数据。用 `tmp_path` 并通过
`lemony_storage_helper.database.sqlite.set_relative_path_base(tmp_path)` 重定向存储根目录。
