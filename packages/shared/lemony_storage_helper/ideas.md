我已经读了 [`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:1)、现有数据库 helper、测试和几个使用点；没有改动代码。

## 对现有内容的看法

[`lemony_storage_helper`](packages/shared/lemony_storage_helper/pyproject.toml:1) 目前的方向是清楚的：从旧的 database 工具抽离成一个偏“存储基础设施”的共享包，先覆盖异步数据库，再扩到本地文件。

### 已有数据库部分做得比较稳

- [`GenericDatabaseHelper`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/generic.py:38) 已经把异步引擎生命周期、建表、session 获取、同步函数桥接这些基础动作封装起来了。
- [`SqliteDatabaseHelper`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/sqlite.py:45) 做了 SQLite 路径解析、相对路径基准、目录创建和内存数据库支持，和 [`test_sqlite.py`](packages/shared/lemony_storage_helper/tests/test_sqlite.py:20) 里的测试目标一致。
- [`GenericDatabaseHelper.new_base()`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/generic.py:76) 已经实现了 [`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:51) 里“helper 或许应该可以协助用户进行表定义”的一部分；[`GenericAsyncAttrs`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/utils.py:286) 也对应了 [`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:20) 里 awaitable relationship 的类型标注问题。
- 上层启动时通过 [`set_relative_path_base()`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/sqlite.py:28) 把数据库相对路径统一落到项目 [`data`](data) 下，这和 [`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:7) 的设想吻合；目前是在 [`init_modules()`](packages/miraichan/src/miraichan/main.py:44) 中设置的。

### 目前略有割裂的地方

- 数据库路径已经有统一 base，但本地文件还没有。比如 [`mbplugin_recorder`](packages/plugins/mbplugin_recorder/__plugin__.py:15) 的数据库路径是相对的 [`record/recorder.db`](packages/plugins/mbplugin_recorder/__plugin__.py:16)，媒体缓存却写死为 [`data/record/media`](packages/plugins/mbplugin_recorder/__plugin__.py:17)，它绕过了现有 [`set_relative_path_base()`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/sqlite.py:28) 的统一语义。
- [`mbplugin_deeeer`](packages/plugins/mbplugin_deeeer/core.py:130) 直接读 [`data/no_data.png`](data/no_data.png)，旁边也已经写了 TODO：cwd 不一定是项目根，需要统一资源管理器。
- [`lemony_storage_helper.files`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/files/__init__.py:1) 还是空的，但 [`pyproject.toml`](packages/shared/lemony_storage_helper/pyproject.toml:27) 已经给了 files extra，说明本地文件管理是规划中的下一块。
- [`mbplugin_recorder.media_cache_path()`](packages/plugins/mbplugin_recorder/media.py:70) 已经包含一部分“文件安全命名 + 内容哈希路径”的雏形，但它是插件私有逻辑；后面很适合下沉到 [`lemony_storage_helper.files`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/files/__init__.py:1)。

## 对接下来“本地文件管理”的重点想法

我建议不要一开始就做很重的“虚拟文件系统”或全局资源数据库，而是先做一个轻量但语义明确的本地文件层：统一路径、统一索引、统一安全写入、统一资源读取。

### 1. 先区分三类东西

本地文件管理最好先把概念分开，否则会混在一起：

1. **运行期数据文件**  
   例如数据库、缓存文件、下载的媒体、插件生成物。默认落在项目 [`data`](data) 下，允许上层配置 base。

2. **包内静态资源**  
   例如插件自带图片、字体、模板。优先使用 Python package resource 语义，而不是 cwd 相对路径。比如 [`mbplugin_deeeer/resources`](packages/plugins/mbplugin_deeeer/resources) 里的图片，语义上不该复制到全局 [`data`](data) 才能读。

3. **用户可替换资源 / 外部资源**  
   例如默认头像 [`data/no_data.png`](data/no_data.png)、字体 [`data/fonts`](data/fonts)，这类可能既要有默认值，也允许用户覆盖。

这三类 API 不该完全一样。运行期文件需要写入和索引；包内资源多数只读；用户资源需要“先找用户目录，没有则 fallback 到包内默认”。

### 2. 建议做一个统一的本地文件 manager，而不是只做若干工具函数

可以参考 [`SettingsManager`](packages/shared/lemony_settings/src/lemony_settings/manager.py:13) 的风格，做一个全局可初始化的 storage/file manager。它的职责类似：

- 管理 data root，例如项目 [`data`](data)。
- 按 identifier / namespace 隔离插件文件。
- 提供路径解析，但默认不随便创建文件。
- 提供安全写入、读取、删除、exists、stat、list。
- 可选提供索引数据库。

目录结构可以类似：

```text
数据根/
  global/
  recorder/
    default/
      media/
      recorder.db
  deeeer/
    default/
      ...
```

不过我更倾向于明确区分逻辑域，例如：

```text
data/
  db/
    recorder/recorder.db
  files/
    recorder/media/...
  cache/
    recorder/media/...
  resources/
    user-overrides/...
```

这样比现在 [`record/recorder.db`](packages/plugins/mbplugin_recorder/__plugin__.py:16) 和 [`data/record/media`](packages/plugins/mbplugin_recorder/__plugin__.py:17) 混用更容易维护。

### 3. 文件 API 的核心应是“受控路径”，而不是裸 [`Path`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/sqlite.py:7)

本地文件 helper 最重要的是避免路径穿越、cwd 假设和插件互相污染。建议 API 不直接让插件拼完整路径，而是让插件请求逻辑路径：

- identifier：插件或模块名，例如 recorder。
- namespace：默认 default，可用于多账号、多环境、多数据集。
- category：db / cache / file / resource / temp。
- key/path：相对路径片段。

关键规则：

- 所有相对路径最终必须 resolve 后仍在 root 内。
- 禁止空路径、绝对路径、带 drive 的路径、越界的 `..`。
- 文件名提供 sanitize 工具，但不要默默把恶意路径“修好”到另一个路径；涉及目录时宁可抛错。
- 写入默认走临时文件 + 原子 replace。
- 大文件读写只提供 async stream 或 chunk API，避免一次性读入内存。

### 4. 索引数据库可以有，但建议第二阶段再做

[`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:59) 提到“直接写入特定的文件，但提供封装的文件索引”，[`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:61) 又提到可能需要 [`global.db`](packages/shared/lemony_storage_helper/devnote.md:61)。我的看法：索引很有价值，但一开始别让所有文件操作强依赖全局数据库。

推荐分两层：

#### 第一阶段：无索引也可用

提供：

- resolve path
- async read/write
- atomic write
- exists/stat/delete
- list
- temporary file
- content hash
- safe suffix / filename

这能立刻替换 [`mbplugin_deeeer`](packages/plugins/mbplugin_deeeer/core.py:130) 这种 cwd 相对路径，也能改造 [`mbplugin_recorder.media_cache_path()`](packages/plugins/mbplugin_recorder/media.py:70) 的路径生成。

#### 第二阶段：可选索引

索引表记录：

- file id
- identifier / namespace / category
- logical path
- physical path
- sha256
- size
- mime type
- suffix
- created_at / updated_at / accessed_at
- source url / source id，可选
- ref_count / tags，可选

对于媒体缓存、去重、清理、迁移很有用。尤其 [`download_media_source()`](packages/plugins/mbplugin_recorder/media.py:89) 已经在算 sha256、mime、size，这些字段可以自然进入索引。

但是索引必须允许“文件存在但索引缺失”和“索引存在但文件缺失”的修复流程，否则实际运行中会很脆。

### 5. 媒体文件管理可以参考 QQ/NapCat，但不要照搬目录语义

[`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:61) 提到参考 QQ 放媒体文件。我觉得可以借鉴两点：

- 内容寻址：文件名优先用 sha256 或平台 file_id，减少重复下载。
- 类型分桶：image / video / audio / file 分目录，便于人工检查和清理。

但不要把“平台侧 ID”作为唯一真实文件名，因为：

- 不同协议的 file_id 可能格式不同。
- URL 下载可能没有稳定 file_id。
- 同内容不同来源应该能去重。
- 后缀应来自魔数检测，而不是盲信 URL。

这部分 [`mbplugin_recorder.media_cache_path()`](packages/plugins/mbplugin_recorder/media.py:70) 和 [`download_media_source()`](packages/plugins/mbplugin_recorder/media.py:89) 已经是一个不错的试验田。后续可以把 `_safe_suffix`、magic 检测、sha256 命名、临时下载、原子落盘这些下沉到 shared。

### 6. 资源读取管理建议独立成 resource resolver

[`devnote.md`](packages/shared/lemony_storage_helper/devnote.md:63) 提到 `{proj_root}/data` 和 `{pkg}/resources` 的混乱。我的建议是做一个 resolver，而不是强行把所有资源搬到同一个目录。

理想行为：

1. 用户覆盖目录优先，例如 [`data/resources`](data)。
2. 包内资源 fallback，例如 [`packages/plugins/mbplugin_deeeer/resources`](packages/plugins/mbplugin_deeeer/resources)。
3. 返回一个可读路径或 async bytes。

API 语义可以是：

- “给我某插件的运行期文件路径”
- “给我某包的静态资源”
- “给我可覆盖资源，用户没放就用默认资源”

这样 [`data/no_data.png`](data/no_data.png) 可以逐步迁移到更清晰的位置，同时不破坏已有调用。

### 7. 和数据库 helper 的关系

我建议本地文件管理不要直接塞进 [`SqliteDatabaseHelper`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/sqlite.py:45)，而是在 [`lemony_storage_helper`](packages/shared/lemony_storage_helper/pyproject.toml:1) 里并列：

- [`lemony_storage_helper.database`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/__init__.py:1)：数据库。
- [`lemony_storage_helper.files`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/files/__init__.py:1)：运行期文件。
- 未来可以有 `resources` 子模块，或者放在 files 下。

不过它们应该共享同一个上层 data root。现在只有 [`set_relative_path_base()`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/sqlite.py:28) 管 SQLite，后续最好抽象成 storage root，而不是 database 专属 root。数据库 helper 可以继续支持自己的 relative base，但默认从全局 storage root 派生。

## 建议实现顺序

1. 先补 [`lemony_storage_helper.files`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/files/__init__.py:1) 的基础 path resolver 和 async 文件读写。
2. 抽一个全局 storage root 初始化函数，让 [`init_modules()`](packages/miraichan/src/miraichan/main.py:44) 同时影响数据库和文件。
3. 把 [`mbplugin_deeeer`](packages/plugins/mbplugin_deeeer/core.py:130) 的 [`data/no_data.png`](data/no_data.png) 读取迁到 resource resolver。
4. 把 [`mbplugin_recorder.media_cache_path()`](packages/plugins/mbplugin_recorder/media.py:70) 的安全后缀、sha256 命名、原子写入逻辑逐步下沉。
5. 再做可选索引库和清理策略，不要第一版就绑定全局索引。

总体上，我觉得这个包目前数据库侧已经有了可用的骨架；接下来本地文件管理的重点不应是"封装 aiofiles"本身，而是统一路径语义、隔离插件数据、避免 cwd 相对路径、提供原子写入和为未来索引/去重留接口。

---

## 数据库 Schema 迁移：集成 Alembic 编程式 API

### 背景

目前 [`GenericDatabaseHelper.startup()`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/generic.py:121) 只做 `metadata.create_all(checkfirst=True)`——表不存在就建，已存在就跳过。对已有表不做任何增量变更。加索引、加字段、改约束都得插件自己写 raw SQL + `sqlite3` 迁移脚本（如 [`mbplugin_deeeer/migration.py`](packages/plugins/mbplugin_deeeer/migration.py)），且缺乏版本追踪。

### 可行性：Alembic 完全可以纯编程式调用

Alembic 的核心 API 不需要任何 `.ini` 配置、`env.py` 脚本或 `versions/` 目录。三个关键 API：

| API | 作用 |
|---|---|
| [`MigrationContext.configure(connection)`](https://alembic.sqlalchemy.org/en/latest/api/runtime.html) | 配置迁移上下文，只需要一个 SA Connection |
| [`produce_migrations(context, metadata)`](https://alembic.sqlalchemy.org/en/latest/api/autogenerate.html) | 对比 database ↔ metadata，生成 `MigrationScript`（含 upgrade_ops / downgrade_ops） |
| [`Operations(context)`](https://alembic.sqlalchemy.org/en/latest/api/runtime.html) + `op.invoke(elem)` | 执行自动生成的迁移操作 |

对 SQLite 的特殊处理：`ModifyTableOps` 需要用 [`batch_alter_table`](https://alembic.sqlalchemy.org/en/latest/ops.html) 包裹，因为 SQLite 不支持完整的 ALTER TABLE。

这意味着可以在 `GenericDatabaseHelper.startup()` 中**直接在 `create_all` 之前**跑一轮 `produce_migrations` → 自动应用差异。

### 设计方案

#### 方案：在 startup 中内置 autogenerate + apply（一键式）

不引入 migration version 元表，直接利用 Alembic 的 `produce_migrations` 对比"当前数据库的实际 schema"与"代码中 SQLAlchemy metadata 声明的 target schema"，自动生成并应用差异。

**核心逻辑**（伪代码）：

```python
from alembic.autogenerate import produce_migrations
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.operations.ops import ModifyTableOps

class GenericDatabaseHelper:
    async def startup(self, *, echo=False, auto_migrate=False, **kw):
        ...
        await self._ensure_engine(echo=echo, **kw)

        if auto_migrate:
            await self._apply_autogenerate()

        # 原有的 create_all（处理全新表）
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all, checkfirst=True)

    async def _apply_autogenerate(self):
        """auto-migrate: compare code metadata vs live database, apply diffs."""
        async with self._engine.connect() as conn:
            # 注意：需要同步 run_sync 因为 MigrationContext.configure 是同步的
            def _do(connection):
                mc = MigrationContext.configure(connection)
                diff = produce_migrations(mc, self._metadata)
                op = Operations(mc)
                self._invoke_ops(op, diff.upgrade_ops, connection.engine)
            await conn.run_sync(_do)

    @staticmethod
    def _invoke_ops(op, ops, engine):
        """递归执行迁移操作栈，SQLite 自动走 batch_alter_table。"""
        use_batch = engine.name == "sqlite"
        stack = [ops]
        while stack:
            elem = stack.pop(0)
            if use_batch and isinstance(elem, ModifyTableOps):
                with op.batch_alter_table(elem.table_name, schema=elem.schema) as batch:
                    for sub in elem.ops:
                        batch.invoke(sub)
            elif hasattr(elem, "ops"):
                stack.extend(elem.ops)
            else:
                op.invoke(elem)
```

#### 使用方式

```python
# 插件侧 —— 启用自动迁移，一行即可
await deerdbcore.startup(auto_migrate=True)
```

或通过配置控制：

```python
auto_migrate = logger.level == logging.DEBUG  # 仅调试模式开启
await deerdbcore.startup(echo=debug, auto_migrate=auto_migrate)
```

#### 优缺点

**优点**：

- 零配置，不需要 migration 版本文件、不需要 `alembic.ini`
- 开发时改了 model 定义 → 重启即自动应用差异（加列、加索引、加约束等）
- `produce_migrations` 生成的 diff 是完整的三态对比（add / drop / modify），比手写 raw SQL 更可靠
- `batch_alter_table` 自动处理 SQLite 的 recreate 重建表流程

**缺点 / 风险**：

- **没有版本追踪**：无法知道"这个数据库已经迁移到了什么状态"，重启重跑完全依赖 Alembic 的幂等性（大部分操作是幂等的，但不绝对）
- **无降级能力**：`produce_migrations` 只产生 upgrade_ops，不做 downgrade
- **无显式审计**：没有 migration history 表，无法确认谁在何时跑了什么迁移
- **危险操作无拦截**：`produce_migrations` 可能生成 drop_column / drop_table 等破坏性操作，需要额外过滤
- **第一次跑可能很慢**：autogenerate 需要 reflect 整个数据库 schema

#### 缓解措施建议

1. **默认 `auto_migrate=False`**，显式 opt-in，避免意外破坏生产数据
2. **提供一个 `--auto-migrate` CLI flag** 或配置项，让运维有主动权
3. **过滤破坏性 ops**：在 `_invoke_ops` 中跳过 `DropTableOp` / `DropColumnOp`，或打印 warning 后 ask confirmation
4. **可选 dry-run**：提供 `auto_migrate_dry_run=True`，只生成 diff 日志，不实际执行
5. **后期可选加元表**：如果未来需要版本追踪，可以在 `_apply_autogenerate` 之前查/写 `_alembic_version` 表，不改变对外 API

#### 与手写 migration.py 的关系

Alembic autogenerate 可以**取代大部分手写迁移**，但不是全部：

- **加索引** ✅ autogenerate 检测到
- **加列** ✅ autogenerate 检测到（SQLite 走 batch recreate）
- **改列类型** ⚠️ autogenerate 会尝试，但 SQLite 实际不支持，batch recreate 可能丢约束
- **数据迁移**（如 `UPDATE ... SET new_col = old_col * 2`） ❌ autogenerate 只做 DDL，不做 DML

对于需要数据迁移的场景，仍可保留手写 `migration.py`，跑在 autogenerate 之后（即在 `startup()` 中拆成三步：auto-migrate DDL → create_all → manual DML migration）。

#### 依赖

Alembic 需要加入 `lemony_storage_helper` 的 `pyproject.toml` 的数据库依赖中（`[project.optional-dependencies]` 的 `database` extra 或新开 `migration` extra）：

```toml
[project.optional-dependencies]
database = ["sqlmodel", "aiosqlite"]
migration = ["alembic"]
```

或者直接把 alembic 放进 database extra，因为它几乎是 SQLAlchemy 生态的事实标准。

### 实现建议

1. 先在 [`GenericDatabaseHelper`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/generic.py:38) 里加 `_apply_autogenerate` 方法
2. [`SqliteDatabaseHelper`](packages/shared/lemony_storage_helper/src/lemony_storage_helper/database/sqlite.py:45) 继承即可，无需覆盖（`batch_alter_table` 判断已内置在 `_invoke_ops` 里）
3. 在 [`mbplugin_deeeer`](packages/plugins/mbplugin_deeeer/__plugin__.py:115) 中试点 `auto_migrate=True`，让 deeeer 成为第一个吃螃蟹的插件
4. 验证后推广到 [`mbplugin_recorder`](packages/plugins/mbplugin_recorder/__plugin__.py) 等
