from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import MetaData
from sqlalchemy.orm import registry
from sqlmodel import SQLModel as _SQLModel

from .core import DatabaseHelper
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
    "DatabaseHelper",
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
    "queryable",
    # 重导出
    "SQLModel",
    "registry",
    "MetaData",
]

if TYPE_CHECKING:

    class SQLModel(_SQLModel):
        __tablename__: ClassVar[str]  # type: ignore
else:
    SQLModel = _SQLModel
