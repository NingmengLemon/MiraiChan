# dev note

预期作为曾经的 lemony_utils_legacy.database 模块的继任者

预期只提供异步接口

本地的数据文件默认放在 data/ 下 (可配置), 像 configs/ 那样隔离

使用风格参照 lemony_settings, model 换成 registry, 什么的

sqlmodel 因为上不去下不来卡在这了于是只扮演表定义生成器的角色. 把metadata交给sa之后剩下的工作就全是sa的了.

需要注意的是sqlmodel的表定义默认是全塞进 SQLModel的metadata里的, 但是可以通过这样, 让表定义往指定的metadata里塞.

```py
class MyTable(SQLModel, metadata=..., registry=...):
    pass
```

以及 AsyncAttrs mixin 类的awaitable_attrs 属性应该有类型标注才对, 于是让用户自己把需要await的字段单独再写一遍:

```py
from sqlalchemy.ext.asyncio.session import AsyncAttrs as _AsyncAttrs
# (省略更多import)

class AsyncAttrs(_AsyncAttrs, Generic[T]):
    if TYPE_CHECKING:
        awaitable_attrs: T  # type: ignore

class _ProblemAsyncAttrs:
    # 通常是关系字段需要 await
    problemset: Awaitable["DBProblemSet"]
    tags: Awaitable[list["DBTag"]]

class MyBase(SQLModel, registry=...):
    ... # 这个是必要的, 因为神秘 SQLModel 的行为
    # 或许可以让 helper 帮一下忙

class ProblemEntity(MyBase, AsyncAttrs[_ProblemAsyncAttrs], table=True):
    ...

# 然后插件自己起一个像 lemony_settings 里的 LemonySettings 一样的东西, 把 metadata 丢进去实例化, 后续就从这个obj里拿 AsyncSession 之类的操作
# e.g.
db = LemonyDatabaseHelper(identifier=..., ..., metadata=registry.metadata, ...)

async def some_async_func():
    async with db.get_session() as session:
        ...
```

helper 或许应该可以协助用户进行表定义,

以上是数据库形式的数据访问

预期提供 2 种数据访问方法:

## 文件系统

直接写入特定的文件, 但提供封装的文件索引.

或许可以参考QQ放媒体文件的方式? 看上去还得给这个共享库本身弄一个 global.db?

以及资源文件读取管理, 目前一些放在 {proj_root}/data, 一些放在 {pkg}/resources, 可能得重新考虑?

## database

### sqlite

- [x]

### postgresql?

// TBD

### redis or other cache?

// TBD
