"""deeeer 插件的 schema 迁移, 作为 SqliteDatabaseHelper.startup 的 prepare 回调执行。

与 create_all 处于同一个事务: 任何一步失败都整体回滚, 库保持迁移前的样子。

处理两种既有形态:

- 旧版插件 (melobot 3.2 时代) 的表名为 ``deerrecord``, 列与现行 ``deer_record``
  完全一致: 改名为 ``deer_record``;
- ``deer_record`` 存在但缺少三个二级索引: 补齐。

两张表同时存在时无法判断以哪张为准, 显式报错而不是猜。
列不全的库同样显式报错。
"""

import logging
from enum import Enum, auto

from sqlalchemy import Connection, inspect

logger = logging.getLogger(__name__)

TABLE = "deer_record"
LEGACY_TABLE = "deerrecord"
REQUIRED_COLUMNS: tuple[str, ...] = (
    "id",
    "timestamp",
    "user_id",
    "group_id",
    "combo",
)
# (索引名, 列名), 名字与 SQLModel Field(index=True) 在默认命名约定下生成的一致
REQUIRED_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_deer_record_timestamp", "timestamp"),
    ("ix_deer_record_user_id", "user_id"),
    ("ix_deer_record_group_id", "group_id"),
)


class MigrationResult(Enum):
    """迁移的结局, 用于区分"真的改了"与"本来就没事" """

    FRESH = auto()
    """两张表都不存在, 交给 create_all 新建"""
    RENAMED_LEGACY = auto()
    """旧表已改名, 索引已补齐"""
    INDEXES_ADDED = auto()
    UP_TO_DATE = auto()


class MigrationError(RuntimeError):
    pass


def _check_columns(conn: Connection, table: str) -> None:
    columns = {c["name"] for c in inspect(conn).get_columns(table)}
    absent = [c for c in REQUIRED_COLUMNS if c not in columns]
    if absent:
        raise MigrationError(
            f"表 {table} 缺少列 {', '.join(absent)}, 不是可识别的 deeeer schema"
        )


def _missing_indexes(conn: Connection) -> list[tuple[str, str]]:
    existing = {ix["name"] for ix in inspect(conn).get_indexes(TABLE)}
    return [(name, col) for name, col in REQUIRED_INDEXES if name not in existing]


def migrate(conn: Connection) -> MigrationResult:
    """在给定连接 (已处于事务中) 上执行迁移"""
    tables = set(inspect(conn).get_table_names())
    has_new, has_legacy = TABLE in tables, LEGACY_TABLE in tables

    if has_new and has_legacy:
        raise MigrationError(
            f"{TABLE} 与旧表 {LEGACY_TABLE} 同时存在, 无法判断以哪张为准, 需要手工处理"
        )
    if not has_new and not has_legacy:
        return MigrationResult.FRESH

    renamed = False
    if has_legacy:
        _check_columns(conn, LEGACY_TABLE)
        logger.info("发现旧版表 %s, 改名为 %s", LEGACY_TABLE, TABLE)
        conn.exec_driver_sql(f'ALTER TABLE "{LEGACY_TABLE}" RENAME TO "{TABLE}"')
        renamed = True
    else:
        _check_columns(conn, TABLE)

    missing = _missing_indexes(conn)
    for name, column in missing:
        conn.exec_driver_sql(f'CREATE INDEX "{name}" ON "{TABLE}" ("{column}")')
    if missing:
        logger.info("为 %s 补齐索引: %s", TABLE, ", ".join(n for n, _ in missing))
        # _missing_indexes 每次都新建 inspector, 不会读到改动前的缓存
        if still := _missing_indexes(conn):
            raise MigrationError(
                f"索引补齐后仍然缺失: {', '.join(n for n, _ in still)}"
            )

    if renamed:
        return MigrationResult.RENAMED_LEGACY
    if missing:
        return MigrationResult.INDEXES_ADDED
    return MigrationResult.UP_TO_DATE
