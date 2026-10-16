"""recorder 的 schema 迁移, 作为 SqliteDatabaseHelper.startup 的 prepare 回调执行。

与 create_all 处于同一个事务, 任一步失败整体回滚。处理的既有形态:

- ``recorder_media_source`` 缺少重试相关的两列 (``attempt_count`` / ``next_attempt_at``): 补列;
- ``recorder_media_object.cache_path`` 存的是相对 cwd 的 ``data/record/media/...``:
  改为相对 data 根的 ``record/media/...``, 与其他数据文件的约定一致。

新库 (表都不存在) 什么都不做, 交给 create_all。
"""

import logging

from sqlalchemy import Connection, inspect

logger = logging.getLogger(__name__)

__all__ = ["LEGACY_MEDIA_PREFIX", "MEDIA_PREFIX", "migrate"]

MEDIA_SOURCE = "recorder_media_source"
MEDIA_OBJECT = "recorder_media_object"
LEGACY_MEDIA_PREFIX = "data/record/media/"
MEDIA_PREFIX = "record/media/"

_NEW_COLUMNS = (
    ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
    ("next_attempt_at", "DATETIME"),
)


def migrate(conn: Connection) -> list[str]:
    """在给定连接 (已处于事务中) 上执行迁移, 返回做过的事的说明"""
    done: list[str] = []
    tables = set(inspect(conn).get_table_names())

    if MEDIA_SOURCE in tables:
        columns = {c["name"] for c in inspect(conn).get_columns(MEDIA_SOURCE)}
        for name, ddl in _NEW_COLUMNS:
            if name not in columns:
                conn.exec_driver_sql(
                    f'ALTER TABLE "{MEDIA_SOURCE}" ADD COLUMN "{name}" {ddl}'
                )
                done.append(f"{MEDIA_SOURCE}.{name} added")
        if "next_attempt_at" not in columns:
            conn.exec_driver_sql(
                f'CREATE INDEX IF NOT EXISTS "ix_{MEDIA_SOURCE}_next_attempt_at" '
                f'ON "{MEDIA_SOURCE}" ("next_attempt_at")'
            )

    if MEDIA_OBJECT in tables:
        result = conn.exec_driver_sql(
            f'UPDATE "{MEDIA_OBJECT}" '
            f"SET cache_path = ? || substr(cache_path, ?) "
            f"WHERE cache_path LIKE ? ESCAPE '\\'",
            (
                MEDIA_PREFIX,
                len(LEGACY_MEDIA_PREFIX) + 1,
                LEGACY_MEDIA_PREFIX.replace("_", "\\_") + "%",
            ),
        )
        if result.rowcount:
            done.append(f"{result.rowcount} cache_path rebased to {MEDIA_PREFIX}")

    for line in done:
        logger.info("recorder 迁移: %s", line)
    return done
