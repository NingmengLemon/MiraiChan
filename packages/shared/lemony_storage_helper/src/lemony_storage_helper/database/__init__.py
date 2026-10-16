import warnings

try:
    from sqlalchemy import MetaData
    from sqlalchemy.orm import DeclarativeBase, registry
except ImportError:
    warnings.warn(
        "sqlalchemy and sqlmodel are required for lemony_storage_helper.database. "
    )
    raise

from .generic import GenericDatabaseHelper, StorageStartupError
from .utils import (
    AsyncCallable,
    DatabaseAsyncCallable,
    GenericAsyncAttrs,
    SQLModel,
    auto_begin,
    check_table_existence,
    check_table_existence_sync,
    datetime_column_tzaware,
    get_session,
    in_transaction,
    new_engine,
    new_session_getter,
    queryable,
    to_async,
)

__all__ = [
    "AsyncCallable",
    "DatabaseAsyncCallable",
    "DeclarativeBase",
    "GenericAsyncAttrs",
    "GenericDatabaseHelper",
    "MetaData",
    # 重导出
    "SQLModel",
    "StorageStartupError",
    "auto_begin",
    "check_table_existence",
    "check_table_existence_sync",
    "datetime_column_tzaware",
    "get_session",
    "in_transaction",
    "new_engine",
    "new_session_getter",
    "queryable",
    "registry",
    "to_async",
]

# 特定数据库后端对应的子模块, 有自己的依赖, 比如 sqlite 需要的 aiosqlite
# 这些写在 pyproject.toml 的 optional-dependencies 中, 需要时才安装
# 因此不在 __init__.py 中导出
