import logging
import warnings
from collections.abc import MutableMapping
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sqlalchemy import URL, MetaData

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
        upper_base = _upper_layer_managed_relative_path_base.get()
        if upper_base is not None:
            if relative_path_base is not None:
                logger.warning(
                    "Upper layer is managing relative_path_base (%s), "
                    "ignoring the one provided (%s)",
                    upper_base,
                    relative_path_base,
                )
            relative_path_base = upper_base

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
            database=self._db_path.as_posix() if self._db_path else None,
        )
        super().__init__(dburl, metadata)

    async def startup(self, *, echo: bool = False, **kw: Any) -> None:
        if self._db_path:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # 所有 aiosqlite 都需要 check_same_thread=False
        connect_args = kw.pop("connect_args", {})
        if not isinstance(connect_args, MutableMapping):
            raise ValueError("connect_args must be a dict")
        connect_args.setdefault("check_same_thread", False)
        kw["connect_args"] = connect_args

        await super().startup(echo=echo, **kw)

    @property
    def in_memory(self) -> bool:
        """是否为内存数据库"""
        return self._db_path is None
