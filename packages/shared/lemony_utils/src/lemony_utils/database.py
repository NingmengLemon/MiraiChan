import functools
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    Concatenate,
    Generic,
    ParamSpec,
    Protocol,
    TypeVar,
)

from melobot.typ import AsyncCallable
from sqlalchemy import URL, Column, Connection, DateTime, Table, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.ext.asyncio.session import (
    AsyncAttrs,
    AsyncSession,
    AsyncSessionTransaction,
)
from sqlalchemy.orm import Session

P = ParamSpec("P")
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


class DatabaseAsyncCallable(Protocol[P, T_co]):
    def __call__(
        self, session: AsyncSession, *args: P.args, **kwargs: P.kwargs
    ) -> Awaitable[T_co]: ...


def in_transaction() -> Callable[
    [DatabaseAsyncCallable[P, T]], DatabaseAsyncCallable[P, T]
]:
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
    nested = session.in_transaction()
    async with (session.begin_nested if nested else session.begin)() as t:
        yield t


def to_async(
    maker: Callable[[], AsyncSession],
) -> Callable[[Callable[Concatenate[Session, P], T]], AsyncCallable[P, T]]:
    def deco(func: Callable[Concatenate[Session, P], T]) -> AsyncCallable[P, T]:
        """将执行第一个参数是 Session 的同步函数装饰成异步函数, 运行时会单开一个 AsyncSession"""

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
    return AsyncSession(
        engine, autoflush=autoflush, expire_on_commit=expire_on_commit, **kwargs
    )


def new_session_getter(
    engine: AsyncEngine,
    autoflush: bool = False,
    expire_on_commit: bool = False,
    **kwargs: Any,
) -> Callable[[], AsyncSession]:
    return functools.partial(
        get_session,
        engine=engine,
        autoflush=autoflush,
        expire_on_commit=expire_on_commit,
        **kwargs,
    )


def new_engine(url: str | URL, echo: bool = False, **kwargs: Any) -> AsyncEngine:
    return create_async_engine(url, echo=echo, **kwargs)


def check_table_existence_sync(conn: Connection, table: Table) -> bool:
    return inspect(conn).has_table(table_name=table.name, schema=table.schema)


async def check_table_existence(session: AsyncSession, table: Table) -> bool:
    async_conn = await session.connection()
    existence = await async_conn.run_sync(check_table_existence_sync, table=table)
    return existence


def datetime_column_tzaware(
    *, onupdate: Any | None = None, index: bool = False
) -> Column[datetime]:
    return Column(
        DateTime(timezone=True), nullable=False, onupdate=onupdate, index=index
    )


class GenericAsyncAttrs(AsyncAttrs, Generic[T]):
    if TYPE_CHECKING:
        awaitable_attrs: T  # type: ignore
