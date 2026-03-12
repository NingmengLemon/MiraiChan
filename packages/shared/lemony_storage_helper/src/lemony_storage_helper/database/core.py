import asyncio
import functools
import logging
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Concatenate, Literal, Self, overload

from sqlalchemy import URL, Engine, MetaData, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession as SAAsyncSession
from sqlalchemy.orm import Session as SASession
from sqlalchemy.sql.schema import Table
from sqlalchemy.util import FacadeDict
from sqlmodel import Session as SQLModelSession
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from .utils import AsyncCallable

logger = logging.getLogger(__name__)


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

    @property
    def tables(self) -> FacadeDict[str, Table]:
        return self._metadata.tables

    async def startup(self, *, echo: bool = False, **kw) -> None:
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
        # sqlmodel session 是基于 sqlalchemy session 的浅封装, 因此兼容 sa session
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


_upper_layer_managed_relative_path_base: Path | None = None


def set_relative_path_base(base: str | Path | None) -> None:
    """设置相对路径的基准路径, 这对于上层统一管理路径很有用

    注意: 这会影响所有使用了相对路径的 SqliteDatabaseHelper 实例

    如果你不知道自己在做什么, 就不要调用这个函数,
    直接在创建 SqliteDatabaseHelper 实例时传入 relative_path_base 参数即可"""
    global _upper_layer_managed_relative_path_base
    if base is not None:
        _upper_layer_managed_relative_path_base = Path(base).resolve()
    else:
        _upper_layer_managed_relative_path_base = None


class SqliteDatabaseHelper(GenericDatabaseHelper):
    """storage helper for sqlite databases."""

    def __init__(
        self,
        db_path: str | Path | None,
        # None 记为内存数据库, 这样一来路径和 None 就是同等的选择, 不加默认值
        metadata: MetaData,
        *,
        relative_path_base: str | Path | None = None,
        # 他还是没能忘记他的 relative_path_base
    ) -> None:
        # 显式拒绝空字符串, 避免歧义
        if db_path == "":
            raise ValueError("db_path cannot be empty string, use None for in-memory")
        if _upper_layer_managed_relative_path_base is not None:
            if relative_path_base is not None:
                logger.warning(
                    "Upper layer is managing relative_path_base, ignoring the one provided to SqliteDatabaseHelper"
                )
            relative_path_base = _upper_layer_managed_relative_path_base

        self._db_path = Path(db_path) if db_path else None

        # 只有需要解析相对路径时才处理 base
        if self._db_path and not self._db_path.is_absolute():
            if relative_path_base is None:
                raise ValueError(
                    "relative_path_base is required when db_path is relative"
                )
            self._db_path = Path(relative_path_base) / self._db_path
            self._db_path = self._db_path.resolve()  # 转为绝对路径, 消除 ..
        elif relative_path_base:
            # 提供了 base 但路径已是绝对路径, 可以警告或忽略
            logger.debug("relative_path_base ignored for absolute db_path")
        dburl = URL.create(
            drivername="sqlite+aiosqlite",
            database=str(self._db_path) if self._db_path else None,
        )
        super().__init__(dburl, metadata)

    async def startup(self, *, echo: bool = False, **kw) -> None:
        if self._db_path:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # 所有 aiosqlite 都需要 check_same_thread=False
        kw.setdefault("connect_args", {})["check_same_thread"] = False

        await super().startup(echo=echo, **kw)
