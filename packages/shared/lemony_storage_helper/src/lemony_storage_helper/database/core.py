import asyncio
import logging
from typing import Literal, overload

from sqlalchemy import URL, Engine, MetaData
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession as SAAsyncSession
from sqlalchemy.orm import Session as SASession
from sqlalchemy.sql.schema import Table
from sqlalchemy.util import FacadeDict
from sqlmodel import Session as SQLModelSession
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession


class DatabaseHelper:
    """base class for storage helpers."""

    def __init__(self, dburl: str | URL, metadata: MetaData) -> None:
        self._dburl = dburl
        self._metadata = metadata
        self._initialized = asyncio.Event()
        self._engine: AsyncEngine | None = None
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    def tables(self) -> FacadeDict[str, Table]:
        return self._metadata.tables

    async def startup(self, *, echo: bool = False, **kw) -> None:
        """Start up the storage helper."""
        if self._engine is not None:
            self._logger.warning("Storage helper already started up.")
            return
        try:
            self._engine = create_async_engine(self._dburl, echo=echo, **kw)
        except Exception as e:
            self._logger.exception("Failed to create engine: %s", e)
            raise
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(self._metadata.create_all, checkfirst=True)
        except Exception as e:
            self._logger.exception("Failed to create tables: %s", e)
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
        async_: Literal[True] = ...,
        style: Literal["sqlmodel"] = "sqlmodel",
    ) -> SQLModelAsyncSession: ...
    @overload
    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        async_: Literal[False],
        style: Literal["sqlmodel"] = "sqlmodel",
    ) -> SQLModelSession: ...
    @overload
    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        async_: Literal[True] = ...,
        style: Literal["sqlalchemy"],
    ) -> SAAsyncSession: ...
    @overload
    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        async_: Literal[False],
        style: Literal["sqlalchemy"],
    ) -> SASession: ...

    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        async_: bool = True,
        style: Literal["sqlmodel", "sqlalchemy"] = "sqlmodel",
    ) -> SQLModelAsyncSession | SAAsyncSession | SQLModelSession | SASession:
        """Get a new AsyncSession.

        用完记得释放, 推荐使用(异步)上下文管理器"""
        if async_:
            session_class = (
                SQLModelAsyncSession if style == "sqlmodel" else SAAsyncSession
            )
            return session_class(
                self.engine,
                autoflush=autoflush,
                expire_on_commit=expire_on_commit,
            )
        else:
            session_class = SQLModelSession if style == "sqlmodel" else SASession
            return session_class(
                self.engine.sync_engine,
                autoflush=autoflush,
                expire_on_commit=expire_on_commit,
            )

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
