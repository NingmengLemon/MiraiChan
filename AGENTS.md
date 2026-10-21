# AGENTS.md

基于 melobot 的 QQ bot, uv workspace monorepo, Python 3.12。结构与开发说明见 `README.md`, 文档索引见 `docs/README.md`。

## 常用命令

- 安装: `just install` (`uv sync --all-packages --all-groups`)
- 测试: `uv run pytest` (仓库根)
- 类型检查 / lint: `uv run ty check <path>`、`uv run ruff check <path>`; 配置在根 `pyproject.toml`
  的 `[tool.ruff]` / `[tool.ty]`。抑制 ty 诊断用 `# ty: ignore[rule]`, mypy 的 `# type: ignore[code]` ty 不认。
  格式化用 `uv run ruff format .`。已跟踪文件的 ruff check / ruff format --check / ty check 均为 0 诊断, 提交前保持住。
- 运行: `just dev` / `just run`, 需要根目录 `config.json` (参考 `config.example.json`)
- 排查与测试时不要直接跑入口文件或 `miraichan launch`: 它们会按 `config.json` 连真实实现端。
  需要完整实例时把 `MIRAICHAN_PROJECT_ROOT` 指到临时目录, 或用 `tools/rehearse_*.py`。

## 约定

- 插件测试放 `tests/plugins/`, 不放插件目录, 原因见 `docs/development/testing.md`。
- 新增 workspace 成员要同时改根 `pyproject.toml` 的 `dependencies`、`[tool.uv.workspace].members`、`[tool.uv.sources]` 三处。
- 代码注释与文档用中文, commit message 用英文 Conventional Commits。
- 日志一律用 `logging.getLogger(__name__)`, 不要按"当前是否 debug"分支, 级别由全局配置控制, 见 `docs/development/logging.md`。
- 插件的 `on_ready` 里的异常会被 melobot 吞掉; 初始化失败要自己记状态, 让 handler 放弃而不是挂起。
- 数据文件路径用 `lemony_storage_helper.files.data_path(...)` (配置项里的路径用 `configured_data_path`),
  不要写 `"data/..."` 这种依赖 cwd 的相对路径; 插件自带的静态资源用
  `resource_path(Path(__file__).parent / "resources", "名字", identifier="quote")`,
  这样用户可以在 `data/resources/<identifier>/` 下放同名文件覆盖 (`identifier` 是不带
  `mbplugin_` 前缀的插件名)。
- 凭据 (access token、API key 等) 不进 `config.json` / `configs/`: 用 `lemony_settings.get_secret`
  从凭据文件 (`credentials.json`) 或环境变量读。
- 文档跟着实现走: 同一阶段里改了行为、配置项、指令或协议事实, 就在同一批提交里更新对应文档;
  文档不写本机绝对路径 (用仓库相对路径或"隔壁某仓库"这种说法)。
- 完成一个大阶段后, 派发拥有*全新上下文*的子代理 (不能是当前会话的 fork) 对这一阶段的工作做 code review, 明确要求它先加载 `code-review`
  技能 (来自 `mattpocock/skills`), 按技能里的"标准 + 需求"两轴分别审查; 评审发现的问题在合并前处理。

## 不要动的东西

- `data/`: 含真实数据库 (`data/record/*.db`), 测试和脚本不得写入。
- `config.json`、`configs/`: 本地真实配置, 含 QQ 号等现场细节, gitignored, 不要复述其中的值。
- `credentials.json`: 真实凭据 (access token、API key), gitignored, 不要读取或复述其内容。
- `references/`: 外部上游仓库的 clone, 只读参考, 可以 `git pull --ff-only` 更新。
- `packages/plugins/_to_be_migrated/`: gitignored 的待迁移旧插件。
- `docs/discussions/`: gitignored, 含主机与内网细节, 内容不得搬进已跟踪文件。

## 线上

线上实例的迁移与运维记录不进仓库 (放在本机 gitignored 的 `docs/deployment/` 下)。对服务器的操作默认只读;
停启服务、改 unit、动服务器上的数据都要先和用户确认。
