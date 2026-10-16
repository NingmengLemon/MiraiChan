import asyncio
import functools
import logging
import types
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from enum import Enum, auto
from types import MappingProxyType, TracebackType
from typing import Any, Concatenate, Literal, Self, overload

from sqlalchemy import URL, Connection, Engine, MetaData, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession as SAAsyncSession
from sqlalchemy.orm import DeclarativeBase, registry
from sqlalchemy.orm import Session as SASession
from sqlalchemy.sql.schema import Table
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


class StorageStartupError(RuntimeError):
    """storage helper 的 startup 已经失败, 等待方据此放弃而不是继续等待"""


class GenericDatabaseHelper:
    """generic class for storage helpers."""

    def __init__(
        self,
        dburl: str | URL,
        metadata: MetaData,
    ) -> None:
        self._dburl_raw: Any = dburl
        self._dburl = None
        self._metadata = metadata
        # _settled 在 startup 成功或失败时都会被 set, 失败原因记在 _failure,
        # 这样等待方不会因为初始化失败而永久挂起
        self._settled = asyncio.Event()
        self._failure: BaseException | None = None
        self._engine: AsyncEngine | None = None
        # 把一切工作延迟到 startup 时, 在冷调试插件的时候很有用

    def _resolve_dburl(self, raw_dburl: Any) -> URL:
        if not isinstance(raw_dburl, (str, URL)):
            raise TypeError("dburl must be a string or URL")
        dburl = make_url(raw_dburl)
        return dburl

    @staticmethod
    def new_metadata(
        naming_convention: (
            dict[str, str] | None | Literal[_Sentinel.USE_DEFAULT]
        ) = _Sentinel.USE_DEFAULT,
        schema: str | None = None,
    ) -> MetaData:
        if naming_convention is _Sentinel.USE_DEFAULT:
            naming_convention = _DEFAULT_NAMING_CONVENTION
        metadata_kwargs: dict[str, Any] = {}
        if naming_convention is not None:
            metadata_kwargs["naming_convention"] = naming_convention
        if schema is not None:
            metadata_kwargs["schema"] = schema
        metadata = MetaData(**metadata_kwargs) if metadata_kwargs else MetaData()
        return metadata

    @classmethod
    def new_base(
        cls,
        name: str,
        *,
        naming_convention: (
            dict[str, str] | None | Literal[_Sentinel.USE_DEFAULT]
        ) = _Sentinel.USE_DEFAULT,
        schema: str | None = None,
    ) -> tuple[type[SQLModel], registry, MetaData]:
        base_name = f"{name.title().replace('_', '')}Base"
        metadata = cls.new_metadata(
            naming_convention=naming_convention,
            schema=schema,
        )
        isolated_registry = registry(metadata=metadata)
        base = types.new_class(
            base_name,
            (SQLModel,),
            {
                "registry": isolated_registry,
            },
        )
        return base, isolated_registry, metadata

    @classmethod
    def new_sa_base(
        cls,
        name: str,
        *,
        naming_convention: (
            dict[str, str] | None | Literal[_Sentinel.USE_DEFAULT]
        ) = _Sentinel.USE_DEFAULT,
        schema: str | None = None,
    ) -> tuple[type[DeclarativeBase], registry, MetaData]:
        base_name = f"{name.title().replace('_', '')}Base"
        metadata = cls.new_metadata(naming_convention=naming_convention, schema=schema)
        isolated_registry = registry(metadata=metadata)
        base = isolated_registry.generate_base(name=base_name)
        return base, isolated_registry, metadata

    @property
    def tables(self) -> Mapping[str, Table]:
        # SA 2.1 的 FacadeDict 不再是可下标的泛型, 对外只承诺只读映射
        return self._metadata.tables

    def _configure_engine(self, engine: AsyncEngine) -> None:
        """引擎创建后、首次连接前的钩子, 子类用来挂方言相关的事件"""

    async def startup(
        self,
        *,
        echo: bool = False,
        prepare: Callable[[Connection], object] | None = None,
        **kw: Any,
    ) -> None:
        """Start up the storage helper.

        prepare: 在 create_all 之前、同一个事务里执行的同步回调, 用于手写的
        schema 迁移。它抛错时整个事务回滚, helper 进入失败状态。

        失败时异常会向上抛出, 同时记录为失败状态, 之后的 wait_until_initialized
        会抛出 StorageStartupError 而不是永久等待。

        SQL 日志建议通过 logging 的 ``sqlalchemy.engine`` 日志器级别控制,
        echo 参数仅作为显式开关保留。"""
        if self._engine is not None:
            logger.warning("Storage helper already started up.")
            return
        self._failure = None
        self._settled.clear()
        try:
            if not isinstance(self._dburl, URL):
                self._dburl = self._resolve_dburl(self._dburl_raw)
            if not isinstance(self._dburl, URL):
                raise RuntimeError(
                    "database url not resolved yet, or not valid sa URL"
                )
            self._engine = create_async_engine(self._dburl, echo=echo, **kw)
            self._configure_engine(self._engine)
            async with self._engine.begin() as conn:
                if prepare is not None:
                    await conn.run_sync(prepare)
                await conn.run_sync(self._metadata.create_all, checkfirst=True)
        except BaseException as e:
            logger.exception("Storage helper startup failed")
            if self._engine is not None:
                await self._engine.dispose()
                self._engine = None
            self._failure = e
            self._settled.set()
            raise
        self._settled.set()

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
        """Check if the helper has been initialized successfully."""
        return self._settled.is_set() and self._failure is None

    @property
    def startup_failure(self) -> BaseException | None:
        """startup 失败时的异常, 未失败或尚未启动时为 None"""
        return self._failure

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

        用完记得释放, 推荐使用(异步)上下文管理器。

        注意: 作为上下文管理器退出时只关闭会话, 不会提交。读过数据之后再写入时,
        写入会因为没提交的外层事务而静默丢失, 需要写入请用 :meth:`session_scope`"""
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

    @asynccontextmanager
    async def session_scope(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        style: Literal["sqlalchemy", "sqlmodel"] = "sqlmodel",
    ) -> AsyncGenerator[SAAsyncSession | SQLModelAsyncSession]:
        """会话作用域: 正常退出时提交, 出错时回滚, 最后关闭。

        与直接 ``async with get_session()`` 的区别: 后者退出时只关闭会话。
        会话里一旦有过读取, SQLAlchemy 会自动开始一个事务, 之后的 ``auto_begin``
        只加 savepoint; 若没人提交外层事务, 退出时这些写入会随事务一起回滚, 且不报错。
        需要写入时一律用这个作用域 (或自己显式 ``session.begin()``)。
        """
        session = self.get_session(
            autoflush=autoflush, expire_on_commit=expire_on_commit, style=style
        )
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()

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
        # 因此理论上兼容 sa session
        async with self.get_session(style="sqlmodel") as asess, asess.begin():
            return await asess.run_sync(func, *args, **kwargs)

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

    async def wait_until_initialized(self, timeout: float | None = None) -> None:
        """等待 startup 结束。

        startup 失败时抛出 StorageStartupError (原异常作为 __cause__);
        超时抛出 TimeoutError。"""
        async with asyncio.timeout(timeout):
            await self._settled.wait()
        if self._failure is not None:
            raise StorageStartupError("storage helper failed to start up") from (
                self._failure
            )

    async def close(self) -> None:
        """Close the storage helper. 未启动时调用是空操作"""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        self._failure = None
        self._settled.clear()

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
