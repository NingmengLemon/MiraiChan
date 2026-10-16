import logging
import warnings
from collections.abc import Callable, MutableMapping
from contextvars import ContextVar
from enum import Enum, auto
from os import PathLike
from pathlib import Path
from typing import Any, Literal, cast, override

from sqlalchemy import URL, Connection, MetaData, event
from sqlalchemy.ext.asyncio import AsyncEngine

from .generic import GenericDatabaseHelper

logger = logging.getLogger(__name__)

try:
    import aiosqlite  # noqa: F401
except ImportError:
    warnings.warn("aiosqlite is not installed, SqliteDatabaseHelper will not work.")
    raise


_upper_layer_managed_relative_path_base: ContextVar[Path | None] = ContextVar(
    "lemony_storage_sqlite_relative_path_base", default=None
)


def set_relative_path_base(base: str | Path | None) -> None:
    """设置相对路径的基准路径, 这对于上层统一管理路径很有用

    注意: 这会影响所有使用了相对路径的 SqliteDatabaseHelper 实例

    如果你不知道自己在做什么, 就不要调用这个函数,
    直接在创建 SqliteDatabaseHelper 实例时传入 relative_path_base 参数即可"""
    if base is not None:
        _upper_layer_managed_relative_path_base.set(Path(base).resolve())
    else:
        _upper_layer_managed_relative_path_base.set(None)


def get_relative_path_base() -> Path | None:
    """上层统一设置的数据根目录, 未设置时为 None。

    数据库之外的数据文件 (字体、存档等) 暂时也以它为根, 直到 storage helper
    的文件管理落地。"""
    return _upper_layer_managed_relative_path_base.get()


class _Sentinel(Enum):
    NOT_RESOLVED = auto()


class SqliteDatabaseHelper(GenericDatabaseHelper):
    """storage helper for sqlite databases."""

    def __init__(
        self,
        db_path: PathLike[str] | str | None,
        # None 记为内存数据库, 这样一来路径和 None 就是同等的选择, 不加默认值
        metadata: MetaData,
        *,
        relative_path_base: str | Path | None = None,
        # 他还是没能忘记他的 relative_path_base
        busy_timeout: float = 15.0,
    ) -> None:
        """busy_timeout: 等待其他写者释放锁的秒数"""
        super().__init__(_Sentinel.NOT_RESOLVED, metadata)  # ty: ignore[invalid-argument-type]
        if busy_timeout < 0:
            raise ValueError("busy_timeout must be non-negative")
        self._busy_timeout_ms = int(busy_timeout * 1000)
        self._relative_path_base = relative_path_base
        self._dburl_raw = db_path
        self._db_path: PathLike[str] | Literal[_Sentinel.NOT_RESOLVED] | None = (
            _Sentinel.NOT_RESOLVED
        )

    @override
    def _resolve_dburl(self, raw_dburl: Any) -> URL:
        if raw_dburl is not None and not isinstance(raw_dburl, (PathLike, str)):
            raise TypeError("database path must be a PathLike object or None")
        db_path_raw = cast(PathLike[str] | str | None, raw_dburl)
        # 显式拒绝空字符串, 避免歧义
        if db_path_raw == "":
            raise ValueError(
                "database path cannot be empty string, use None for in-memory"
            )
        upper_base = _upper_layer_managed_relative_path_base.get()
        if upper_base is not None:
            if self._relative_path_base is not None:
                logger.warning(
                    "Upper layer is managing relative_path_base (%s), "
                    "ignoring the one provided (%s)",
                    upper_base,
                    self._relative_path_base,
                )
            self._relative_path_base = upper_base

        db_path = Path(db_path_raw) if db_path_raw is not None else None

        # 只有需要解析相对路径时才处理 base
        if db_path is not None and not db_path.is_absolute():
            if self._relative_path_base is None:
                raise ValueError(
                    "relative_path_base is required when db_path is relative"
                )
            db_path = Path(self._relative_path_base) / db_path
            db_path = db_path.resolve()  # 转为绝对路径, 消除 ..
        elif self._relative_path_base:
            # 提供了 base 但路径已是绝对路径, 可以警告或忽略
            logger.debug("relative_path_base ignored for absolute db_path")
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        dburl = URL.create(
            drivername="sqlite+aiosqlite",
            database=db_path.as_posix() if db_path is not None else None,
        )
        return dburl

    @override
    async def startup(
        self,
        *,
        echo: bool = False,
        prepare: Callable[[Connection], object] | None = None,
        **kw: Any,
    ) -> None:
        # 所有 aiosqlite 都需要 check_same_thread=False
        connect_args = kw.pop("connect_args", {})
        if not isinstance(connect_args, MutableMapping):
            raise ValueError("connect_args must be a dict")
        connect_args.setdefault("check_same_thread", False)
        kw["connect_args"] = connect_args

        await super().startup(echo=echo, prepare=prepare, **kw)

    @override
    def _configure_engine(self, engine: AsyncEngine) -> None:
        sync_engine = engine.sync_engine
        busy_timeout_ms = self._busy_timeout_ms
        use_wal = not self.in_memory

        @event.listens_for(sync_engine, "connect")
        def _on_connect(dbapi_connection: Any, _record: Any) -> None:
            # 关掉驱动自己的事务管理, 否则驱动只在 DML 前才发 BEGIN,
            # SELECT 之后的 SAVEPOINT 会落在事务外, RELEASE 时直接提交,
            # 外层 rollback 撤不回来。见 SQLAlchemy sqlite 方言文档
            # "Serializable isolation / Savepoints / Transactional DDL"
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout = {busy_timeout_ms:d}")
                cursor.execute("PRAGMA foreign_keys = ON")
                if use_wal:
                    cursor.execute("PRAGMA journal_mode = WAL")
                    cursor.execute("PRAGMA synchronous = NORMAL")
            finally:
                cursor.close()

        @event.listens_for(sync_engine, "begin")
        def _on_begin(conn: Connection) -> None:
            # IMMEDIATE: 开事务时就拿写锁, 并发写者在 busy_timeout 内排队,
            # 避免 DEFERRED 事务读后升级写锁时直接报 database is locked
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    @property
    def in_memory(self) -> bool:
        """是否为内存数据库"""
        if self._db_path is _Sentinel.NOT_RESOLVED:
            raise RuntimeError("Database path has not been resolved")
        return self._db_path is None
