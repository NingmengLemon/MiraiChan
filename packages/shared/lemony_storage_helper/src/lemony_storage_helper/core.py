"""
核心模块: LemonyStorageHelper 主类.

提供类似 lemony_settings 的使用风格, 用于管理数据库连接和会话.
"""

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import Enum, auto
from pathlib import Path
from typing import Any, Literal

from melobot.log import get_logger
from sqlalchemy import URL, MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from .utils import auto_begin

__all__ = [
    "LemonyStorageHelper",
    "GlobalStorageSettings",
    "init_global_storage_settings",
    "get_global_storage_settings",
    "require",
    "resolve_data_path",
]

logger = get_logger()

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][0-9A-Za-z_]{0,31}$")

_STORAGE_TABLE: dict[str, "LemonyStorageHelper"] = {}
_global_storage_settings: "GlobalStorageSettings | None" = None


class _Sentinel(Enum):
    NOT_INITIALIZED = auto()


class DatabaseType(Enum):
    """支持的数据库类型."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


class LemonyStorageHelper:
    """
    数据库存储帮助类.

    管理异步数据库引擎和会话, 提供便捷的数据库操作接口.

    用法示例:
        from sqlalchemy.orm import registry
        from sqlmodel import SQLModel

        # 创建 registry 和 metadata
        my_registry = registry()
        my_metadata = my_registry.metadata

        # 定义表模型
        class MyTable(SQLModel, registry=my_registry, metadata=my_metadata, table=True):
            id: int = Field(primary_key=True)
            name: str

        # 创建存储帮助实例
        db = LemonyStorageHelper(
            identifier="my_plugin",
            metadata=my_metadata,
        )

        # 初始化数据库
        await db.init()

        # 使用会话
        async with db.session() as session:
            ...
    """

    def __init__(
        self,
        identifier: str,
        metadata: MetaData,
        *,
        db_type: DatabaseType | None = None,
        db_url: str | URL | None = None,
        db_name: str | None = None,
        echo: bool = False,
        engine_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """
        初始化存储帮助实例.

        Args:
            identifier: 唯一标识符, 用于命名数据库文件等.
            metadata: SQLAlchemy MetaData 对象, 包含表定义.
            db_type: 数据库类型 (sqlite/postgresql), 默认使用全局设置.
            db_url: 完整的数据库连接 URL, 如果提供则忽略 db_type 和 db_name.
            db_name: 数据库名称 (仅用于 sqlite, 默认为 identifier).
            echo: 是否启用 SQL 日志输出.
            engine_kwargs: 传递给 create_async_engine 的额外参数.
        """
        self._identifier = self._check_pattern_match(IDENTIFIER_PATTERN, identifier)
        self._metadata = metadata
        self._db_type = db_type
        self._db_url = db_url
        self._db_name = db_name or identifier
        self._echo = echo
        self._engine_kwargs = engine_kwargs or {}

        self._engine: AsyncEngine | Literal[_Sentinel.NOT_INITIALIZED] = (
            _Sentinel.NOT_INITIALIZED
        )
        self._initialized = False

        # 注册到全局表
        if identifier in _STORAGE_TABLE:
            raise ValueError(
                f"Storage helper with identifier '{identifier}' already exists."
            )
        _STORAGE_TABLE[identifier] = self

    def _check_pattern_match(self, pattern: str | re.Pattern, value: str) -> str:
        if re.fullmatch(pattern, value) is None:
            raise ValueError(f"Value '{value}' does not match the pattern '{pattern}'")
        return value

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def id(self) -> str:
        return self._identifier

    @property
    def metadata(self) -> MetaData:
        return self._metadata

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is _Sentinel.NOT_INITIALIZED:
            raise RuntimeError(
                f"Storage helper '{self._identifier}' has not been initialized yet. "
                "Call init() first."
            )
        return self._engine

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def _build_db_url(self) -> str | URL:
        """构建数据库连接 URL."""
        if self._db_url is not None:
            return self._db_url

        global_settings = get_global_storage_settings()
        db_type = self._db_type or global_settings.db_type

        if db_type == DatabaseType.SQLITE:
            data_path = resolve_data_path(
                global_settings.data_path,
                self._identifier,
            )
            db_file = data_path / f"{self._db_name}.db"
            return f"sqlite+aiosqlite:///{db_file}"

        elif db_type == DatabaseType.POSTGRESQL:
            pg_settings = global_settings.postgresql
            if pg_settings is None:
                raise ValueError(
                    "PostgreSQL settings not configured in global storage settings."
                )
            return URL.create(
                drivername="postgresql+asyncpg",
                username=pg_settings.get("username"),
                password=pg_settings.get("password"),
                host=pg_settings.get("host", "localhost"),
                port=pg_settings.get("port", 5432),
                database=pg_settings.get("database", self._db_name),
            )

        raise ValueError(f"Unsupported database type: {db_type}")

    async def init(self, *, create_tables: bool = True) -> None:
        """
        初始化数据库引擎并创建表.

        Args:
            create_tables: 是否自动创建表, 默认为 True.
        """
        if self._initialized:
            logger.warning(
                f"Storage helper '{self._identifier}' is already initialized."
            )
            return

        url = self._build_db_url()
        self._engine = create_async_engine(url, echo=self._echo, **self._engine_kwargs)

        if create_tables:
            async with self._engine.begin() as conn:
                await conn.run_sync(self._metadata.create_all)

        self._initialized = True
        logger.info(f"Storage helper '{self._identifier}' initialized successfully.")

    async def close(self) -> None:
        """关闭数据库引擎并释放连接池."""
        if self._engine is not _Sentinel.NOT_INITIALIZED:
            await self._engine.dispose()
            self._engine = _Sentinel.NOT_INITIALIZED
            self._initialized = False
            logger.info(f"Storage helper '{self._identifier}' closed.")

    @asynccontextmanager
    async def session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[AsyncSession, None]:
        """
        获取一个异步会话的上下文管理器.

        Args:
            autoflush: 是否自动刷新, 默认为 False.
            expire_on_commit: 提交后是否过期对象属性, 默认为 False.
            **kwargs: 传递给 AsyncSession 的额外参数.

        Yields:
            AsyncSession: 异步数据库会话.
        """
        session = AsyncSession(
            self.engine,
            autoflush=autoflush,
            expire_on_commit=expire_on_commit,
            **kwargs,
        )
        try:
            yield session
        finally:
            await session.close()

    @asynccontextmanager
    async def begin(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[AsyncSession, None]:
        """
        获取一个自动管理事务的异步会话上下文管理器.

        在上下文结束时自动提交事务, 出现异常时自动回滚.

        Args:
            autoflush: 是否自动刷新, 默认为 False.
            expire_on_commit: 提交后是否过期对象属性, 默认为 False.
            **kwargs: 传递给 AsyncSession 的额外参数.

        Yields:
            AsyncSession: 异步数据库会话.
        """
        async with self.session(
            autoflush=autoflush, expire_on_commit=expire_on_commit, **kwargs
        ) as session:
            async with auto_begin(session):
                yield session

    def get_session(
        self,
        *,
        autoflush: bool = False,
        expire_on_commit: bool = False,
        **kwargs: Any,
    ) -> AsyncSession:
        """
        创建一个新的异步会话 (不使用上下文管理器).

        注意: 调用者需要自行管理会话的关闭.

        Args:
            autoflush: 是否自动刷新, 默认为 False.
            expire_on_commit: 提交后是否过期对象属性, 默认为 False.
            **kwargs: 传递给 AsyncSession 的额外参数.

        Returns:
            AsyncSession: 异步数据库会话.
        """
        return AsyncSession(
            self.engine,
            autoflush=autoflush,
            expire_on_commit=expire_on_commit,
            **kwargs,
        )


class GlobalStorageSettings:
    """
    全局存储设置.

    用于配置默认的数据库类型和数据存储路径.
    """

    def __init__(
        self,
        data_path: str | Path = "data",
        db_type: DatabaseType = DatabaseType.SQLITE,
        postgresql: dict[str, Any] | None = None,
    ) -> None:
        """
        初始化全局存储设置.

        Args:
            data_path: 数据存储目录, 默认为 "data".
            db_type: 默认数据库类型, 默认为 SQLITE.
            postgresql: PostgreSQL 连接配置 (可选).
        """
        self._data_path = Path(data_path).resolve()
        self._db_type = db_type
        self._postgresql = postgresql

    @property
    def data_path(self) -> Path:
        return self._data_path

    @property
    def db_type(self) -> DatabaseType:
        return self._db_type

    @property
    def postgresql(self) -> dict[str, Any] | None:
        return self._postgresql


def resolve_data_path(data_path: str | Path, identifier: str | None = None) -> Path:
    """
    解析数据存储路径.

    Args:
        data_path: 数据根目录.
        identifier: 存储帮助标识符, 用于创建子目录.

    Returns:
        Path: 解析后的数据路径.
    """
    data_root = Path(data_path).resolve()
    data_root.mkdir(parents=True, exist_ok=True)

    if identifier is None:
        return data_root

    path = data_root / identifier
    path.mkdir(parents=True, exist_ok=True)
    return path


def init_global_storage_settings(
    data_path: str | Path = "data",
    db_type: DatabaseType = DatabaseType.SQLITE,
    postgresql: dict[str, Any] | None = None,
) -> GlobalStorageSettings:
    """
    初始化全局存储设置.

    这个函数应该在程序启动时调用, 且只能调用一次.

    Args:
        data_path: 数据存储目录, 默认为 "data".
        db_type: 默认数据库类型, 默认为 SQLITE.
        postgresql: PostgreSQL 连接配置.

    Returns:
        GlobalStorageSettings: 全局存储设置实例.
    """
    global _global_storage_settings
    if _global_storage_settings is not None:
        raise RuntimeError("GlobalStorageSettings has already been initialized.")

    data_path_resolved = Path(data_path).resolve()
    data_path_resolved.mkdir(parents=True, exist_ok=True)

    _global_storage_settings = GlobalStorageSettings(
        data_path=data_path_resolved,
        db_type=db_type,
        postgresql=postgresql,
    )

    logger.info(
        f"Global storage settings initialized with data_path: {data_path_resolved}"
    )
    return _global_storage_settings


def get_global_storage_settings() -> GlobalStorageSettings:
    """
    获取全局存储设置实例.

    Returns:
        GlobalStorageSettings: 全局存储设置实例.

    Raises:
        RuntimeError: 如果全局设置尚未初始化.
    """
    if _global_storage_settings is None:
        raise RuntimeError("GlobalStorageSettings has not been initialized yet.")
    return _global_storage_settings


def require(identifier: str) -> LemonyStorageHelper:
    """
    获取指定标识符的存储帮助实例.

    Args:
        identifier: 存储帮助的唯一标识符.

    Returns:
        LemonyStorageHelper: 存储帮助实例.

    Raises:
        KeyError: 如果指定标识符的实例不存在.
    """
    if identifier not in _STORAGE_TABLE:
        raise KeyError(f"Storage helper with identifier '{identifier}' not found.")
    return _STORAGE_TABLE[identifier]


def get_all_storage_helpers() -> dict[str, LemonyStorageHelper]:
    """
    获取所有已注册的存储帮助实例.

    Returns:
        dict[str, LemonyStorageHelper]: 标识符到实例的映射.
    """
    return _STORAGE_TABLE.copy()


async def close_all_storage_helpers() -> None:
    """关闭所有已注册的存储帮助实例."""
    for helper in _STORAGE_TABLE.values():
        if helper.is_initialized:
            await helper.close()
    logger.info("All storage helpers closed.")
