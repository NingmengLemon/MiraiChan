"""
工具函数模块.

提供数据库操作相关的辅助函数和装饰器.
"""

import functools
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Concatenate,
    Generic,
    ParamSpec,
    Protocol,
    TypeVar,
    cast,
)

from sqlalchemy import URL, Column, Connection, DateTime, Table, inspect
from sqlalchemy.ext.asyncio import AsyncAttrs as _AsyncAttrs
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.ext.asyncio.session import (
    AsyncSession,
    AsyncSessionTransaction,
)
from sqlalchemy.orm import QueryableAttribute, Session
from sqlmodel import SQLModel as _SQLModel

__all__ = [
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
]

P = ParamSpec("P")
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)

if TYPE_CHECKING:
    # HACK:
    # 子类用 __tablename__ = "xxx" 的方式指定表名时, pylance 会如此说道:
    # Type "Literal['xxx']" is not assignable to declared type "declared_attr[Unknown]"
    # 此问题已知, 总之我就像这样写了)
    # https://github.com/microsoft/pylance-release/issues/2129
    # https://github.com/microsoft/pylance-release/issues/3484
    # https://github.com/fastapi/sqlmodel/issues/98
    class SQLModel(_SQLModel):
        __tablename__: ClassVar[str | Callable[..., str]]  # type: ignore

else:
    SQLModel = _SQLModel


class AsyncCallable(Protocol[P, T_co]):
    """异步可调用协议."""

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[T_co]: ...


class DatabaseAsyncCallable(Protocol[P, T_co]):
    """数据库异步可调用协议, 第一个参数为 AsyncSession."""

    def __call__(
        self, session: AsyncSession, *args: P.args, **kwargs: P.kwargs
    ) -> Awaitable[T_co]: ...


def in_transaction() -> Callable[
    [DatabaseAsyncCallable[P, T]], DatabaseAsyncCallable[P, T]
]:
    """
    装饰器: 将函数包装在事务中执行.

    被装饰的函数应以 AsyncSession 作为第一个参数.
    如果会话已在事务中, 则使用嵌套事务.

    用法示例:
        @in_transaction()
        async def update_user(session: AsyncSession, user_id: int, name: str):
            user = await session.get(User, user_id)
            user.name = name
            await session.flush()
    """

    def deco(func: DatabaseAsyncCallable[P, T]) -> DatabaseAsyncCallable[P, T]:
        @functools.wraps(func)
        async def wrapped(
            session: AsyncSession, *args: P.args, **kwargs: P.kwargs
        ) -> T:
            async with auto_begin(session):
                rv = await func(session, *args, **kwargs)
                return rv

        return wrapped

    return deco


@asynccontextmanager
async def auto_begin(
    session: AsyncSession,
) -> AsyncGenerator[AsyncSessionTransaction, None]:
    """
    自动开始事务的上下文管理器.

    如果会话已在事务中, 则使用嵌套事务 (savepoint);
    否则开始新事务.

    用法示例:
        async with auto_begin(session) as transaction:
            session.add(user)
            await session.flush()
    """
    nested = session.in_transaction()
    async with (session.begin_nested if nested else session.begin)() as t:
        yield t


def to_async(
    maker: Callable[[], AsyncSession],
) -> Callable[[Callable[Concatenate[Session, P], T]], AsyncCallable[P, T]]:
    """
    装饰器工厂: 将同步数据库函数转换为异步函数.

    被装饰的函数应以 (同步) Session 作为第一个参数.
    运行时会自动创建 AsyncSession 并通过 run_sync 执行原函数.

    Args:
        maker: 创建 AsyncSession 的工厂函数.

    用法示例:
        @to_async(session_maker)
        def get_user_sync(session: Session, user_id: int) -> User:
            return session.get(User, user_id)

        # 调用时:
        user = await get_user_sync(user_id)
    """

    def deco(func: Callable[Concatenate[Session, P], T]) -> AsyncCallable[P, T]:
        @functools.wraps(func)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            async with maker() as asess:
                return await asess.run_sync(func, *args, **kwargs)

        return wrapped

    return deco


def get_session(
    engine: AsyncEngine,
    autoflush: bool = False,
    expire_on_commit: bool = False,
    **kwargs: Any,
) -> AsyncSession:
    """
    创建一个新的异步会话.

    Args:
        engine: 异步数据库引擎.
        autoflush: 是否自动刷新, 默认为 False.
        expire_on_commit: 提交后是否过期对象属性, 默认为 False.
        **kwargs: 传递给 AsyncSession 的额外参数.

    Returns:
        AsyncSession: 新创建的异步会话.
    """
    return AsyncSession(
        engine, autoflush=autoflush, expire_on_commit=expire_on_commit, **kwargs
    )


def new_session_getter(
    engine: AsyncEngine,
    autoflush: bool = False,
    expire_on_commit: bool = False,
    **kwargs: Any,
) -> Callable[[], AsyncSession]:
    """
    创建一个会话获取器函数.

    Args:
        engine: 异步数据库引擎.
        autoflush: 是否自动刷新, 默认为 False.
        expire_on_commit: 提交后是否过期对象属性, 默认为 False.
        **kwargs: 传递给 AsyncSession 的额外参数.

    Returns:
        Callable[[], AsyncSession]: 会话获取器函数.
    """
    return functools.partial(
        get_session,
        engine=engine,
        autoflush=autoflush,
        expire_on_commit=expire_on_commit,
        **kwargs,
    )


def new_engine(url: str | URL, echo: bool = False, **kwargs: Any) -> AsyncEngine:
    """
    创建一个新的异步数据库引擎.

    Args:
        url: 数据库连接 URL.
        echo: 是否启用 SQL 日志输出.
        **kwargs: 传递给 create_async_engine 的额外参数.

    Returns:
        AsyncEngine: 新创建的异步引擎.
    """
    return create_async_engine(url, echo=echo, **kwargs)


def check_table_existence_sync(conn: Connection, table: Table) -> bool:
    """
    同步检查表是否存在.

    Args:
        conn: 数据库连接.
        table: 要检查的表对象.

    Returns:
        bool: 表是否存在.
    """
    return inspect(conn).has_table(table_name=table.name, schema=table.schema)


async def check_table_existence(session: AsyncSession, table: Table) -> bool:
    """
    异步检查表是否存在.

    Args:
        session: 异步会话.
        table: 要检查的表对象.

    Returns:
        bool: 表是否存在.
    """
    async_conn = await session.connection()
    existence = await async_conn.run_sync(check_table_existence_sync, table=table)
    return existence


def datetime_column_tzaware(
    *, onupdate: Any | None = None, index: bool = False
) -> Column[datetime]:
    """
    创建一个支持时区的日期时间列.

    Args:
        onupdate: 更新时的默认值.
        index: 是否创建索引.

    Returns:
        Column[datetime]: 日期时间列定义.
    """
    return Column(
        DateTime(timezone=True), nullable=False, onupdate=onupdate, index=index
    )


class GenericAsyncAttrs(_AsyncAttrs, Generic[T]):
    """
    泛型 AsyncAttrs Mixin 类, 用于为关系字段提供类型标注.

    用法示例:
        class _UserAwaitableAttrs:
            groups: Awaitable[list["Group"]]

        class User(Base, GenericAsyncAttrs[_UserAwaitableAttrs], table=True):
            ...
    """

    if TYPE_CHECKING:
        awaitable_attrs: T  # type: ignore


def queryable(o: T) -> QueryableAttribute[T]:
    if not isinstance(o, QueryableAttribute):
        raise TypeError(f"Expected QueryableAttribute, got {type(o)!r}")
    return cast(QueryableAttribute, o)
