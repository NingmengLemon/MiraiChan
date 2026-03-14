import asyncio
import functools
import logging
import types
from collections.abc import Callable
from enum import Enum, auto
from types import MappingProxyType, TracebackType
from typing import Any, Concatenate, Literal, Self, overload

from sqlalchemy import URL, Engine, MetaData, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession as SAAsyncSession
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import registry
from sqlalchemy.sql.schema import Table
from sqlalchemy.util import FacadeDict
from sqlmodel import Session as SQLModelSession
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from .utils import AsyncCallable, SQLModel

logger = logging.getLogger(__name__)

_DEFAULT_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
DEFAULT_NAMING_CONVENTION = MappingProxyType(_DEFAULT_NAMING_CONVENTION)


class _Sentinel(Enum):
    USE_DEFAULT = auto()


class GenericDatabaseHelper:
    """generic class for storage helpers."""

    def __init__(
        self,
        dburl: str | URL,
        metadata: MetaData,
    ) -> None:
        self._dburl = make_url(dburl)
        self._metadata = metadata
        self._initialized = asyncio.Event()
        self._engine: AsyncEngine | None = None

    @classmethod
    def new_base(
        cls,
        name: str,
        *,
        naming_convention: (
            dict[str, str] | None | Literal[_Sentinel.USE_DEFAULT]
        ) = _Sentinel.USE_DEFAULT,
        schema: str | None = None,
    ) -> tuple[type[SQLModel], registry]:
        """
        用于减少样板代码, 因为 SQLModel 的 registry 机制比较麻烦,
        需要先创建一个 registry, 然后再创建一个 base class 来绑定这个 registry.

        如果使用这个方法, 后续的表模型就都继承这个自动生成的 base class 就行了,
        这样就不需要每个模块都写一大段样板代码了
        """
        if naming_convention is _Sentinel.USE_DEFAULT:
            naming_convention = _DEFAULT_NAMING_CONVENTION
        metadata_kwargs: dict[str, Any] = {}
        if naming_convention is not None:
            metadata_kwargs["naming_convention"] = naming_convention
        if schema is not None:
            metadata_kwargs["schema"] = schema
        metadata = MetaData(**metadata_kwargs) if metadata_kwargs else MetaData()
        isolated_registry = registry(metadata=metadata)

        base_name = f"{name.title().replace('_', '')}Base"
        base = types.new_class(
            base_name,
            (SQLModel,),
            {
                "registry": isolated_registry,
                # "metadata": metadata,
                # opus sensei 说这个没必要
            },
        )
        return base, isolated_registry

    @property
    def tables(self) -> FacadeDict[str, Table]:
        return self._metadata.tables

    async def startup(self, *, echo: bool = False, **kw: Any) -> None:
        """Start up the storage helper."""
        if self._engine is not None:
            logger.warning("Storage helper already started up.")
            return

        try:
            self._engine = create_async_engine(self._dburl, echo=echo, **kw)
        except Exception as e:
            logger.exception("Failed to create engine: %s", e)
            raise
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(self._metadata.create_all, checkfirst=True)
        except Exception as e:
            logger.exception("Failed to create tables: %s", e)
            await self.close()
            raise
        self._initialized.set()

    @property
    def engine(self) -> AsyncEngine:
        """Get the AsyncEngine instance."""
        if self._engine is None:
            raise RuntimeError("helper not started up yet.")
        return self._engine

    @property
    def sync_engine(self) -> Engine:
        return self.engine.sync_engine

    def is_initialized(self) -> bool:
        """Check if the helper has been initialized."""
        return self._initialized.is_set()

    @overload
    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        style: Literal["sqlmodel"] = "sqlmodel",
    ) -> SQLModelAsyncSession: ...
    @overload
    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        style: Literal["sqlalchemy"] = "sqlalchemy",
    ) -> SAAsyncSession: ...
    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        style: Literal["sqlalchemy", "sqlmodel"] = "sqlmodel",
    ) -> SAAsyncSession | SQLModelAsyncSession:
        """Get a new AsyncSession.

        用完记得释放, 推荐使用(异步)上下文管理器"""
        return (
            SAAsyncSession(
                self.engine,
                autoflush=autoflush,
                expire_on_commit=expire_on_commit,
            )
            if style == "sqlalchemy"
            else SQLModelAsyncSession(
                self.engine,
                autoflush=autoflush,
                expire_on_commit=expire_on_commit,
            )
        )

    async def run_sync[**P, T](
        self,
        func: Callable[Concatenate[SASession, P], T]
        | Callable[Concatenate[SQLModelSession, P], T],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """单开一个 AsyncSession 来执行第一个参数是 Session 的同步函数"""
        # sqlmodel session 是基于 sqlalchemy session 的浅封装,
        # 且没有 runtime warning, 只是把 sa 的方法用类型注解标成了 deprecated,
        # 因此兼容 sa session
        async with self.get_session(style="sqlmodel") as asess:
            async with asess.begin():
                return await asess.run_sync(func, *args, **kwargs)  # type: ignore

    def to_async[**P, T](
        self,
        func: Callable[Concatenate[SASession, P], T]
        | Callable[Concatenate[SQLModelSession, P], T],
    ) -> AsyncCallable[P, T]:
        """将执行第一个参数是同步 Session 的同步函数装饰成异步函数,
        运行时会单开一个 AsyncSession 及其 transaction"""

        @functools.wraps(func)
        async def wrapped(*args: P.args, **kwargs: P.kwargs):
            return await self.run_sync(func, *args, **kwargs)

        return wrapped

    async def wait_until_initialized(self) -> None:
        """Wait until the helper is initialized."""
        await self._initialized.wait()

    async def close(self) -> None:
        """Close the storage helper."""
        await self.engine.dispose()
        self._engine = None
        self._initialized.clear()

    def get_connection(self) -> AsyncConnection:
        """Get a connection from the engine.

        用完记得释放, 推荐使用 async with"""
        return self.engine.connect()

    async def __aenter__(self) -> Self:
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
