from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import MetaData
from sqlalchemy.orm import registry
from sqlmodel import SQLModel as _SQLModel
from sqlmodel import col

from .core import GenericDatabaseHelper, SqliteDatabaseHelper, set_relative_path_base
from .utils import (
    AsyncCallable,
    DatabaseAsyncCallable,
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
    "GenericDatabaseHelper",
    "SqliteDatabaseHelper",
    "AsyncCallable",
    "DatabaseAsyncCallable",
    "in_transaction",
    "auto_begin",
    "to_async",
    "get_session",
    "new_session_getter",
    "new_engine",
    "check_table_existence_sync",
    "check_table_existence",
    "datetime_column_tzaware",
    "set_relative_path_base",
    "queryable",
    # 重导出
    "SQLModel",
    "registry",
    "MetaData",
    "col",
]

if TYPE_CHECKING:

    class SQLModel(_SQLModel):
        __tablename__: ClassVar[str]  # type: ignore
else:
    SQLModel = _SQLModel
