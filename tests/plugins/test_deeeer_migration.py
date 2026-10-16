"""mbplugin_deeeer schema 迁移的回归测试。

已知答案的样本自检: 旧版 deerrecord 表应被改名并保留全部数据, 缺索引的库应被补齐,
本来就齐全的库什么都不做, 无法识别的形态显式报错且不留半成品。
全部操作都在 tmp_path 下, 不触碰 data/ 下的真实数据。

测试文件不能放在插件包目录里: pytest 会导入插件的 __init__.py 并查询
pytest_plugins 属性, 而 melobot 生成的 __getattr__ 在没有 bot 实例时会抛 BotError。
"""

import sqlite3
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from lemony_storage_helper.database import StorageStartupError
from lemony_storage_helper.database.sqlite import (
    SqliteDatabaseHelper,
    set_relative_path_base,
)
from mbplugin_deeeer.core import (
    DBPPATH,
    deer_metadata,
    deerdbcore,
    query,
    record,
)
from mbplugin_deeeer.migration import (
    REQUIRED_INDEXES,
    MigrationError,
    MigrationResult,
    migrate,
)

REQUIRED_INDEX_NAMES = {name for name, _ in REQUIRED_INDEXES}

# 旧版插件 (SQLModel 默认表名) 实际建出的表, 取自线上旧库的 sqlite_master
LEGACY_TABLE_SQL = """
CREATE TABLE deerrecord (
    id CHAR(32) NOT NULL,
    timestamp FLOAT NOT NULL,
    user_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    combo INTEGER NOT NULL,
    PRIMARY KEY (id)
);
"""
# 现行表名但没有二级索引
UNINDEXED_TABLE_SQL = LEGACY_TABLE_SQL.replace("deerrecord", "deer_record")
# 列不全, 不是可识别的形态
ANCIENT_TABLE_SQL = """
CREATE TABLE deerrecord (
    id CHAR(32) NOT NULL,
    combo INTEGER NOT NULL,
    PRIMARY KEY (id)
);
"""

LEGACY_ROWS = [
    ("0" * 31 + "1", 1700000000.0, 10086, 10010, 1),
    ("0" * 31 + "2", time.time() - 60, 10086, 10010, 3),
    ("a" * 32, time.time() - 30, 10087, 10010, 2),
]


@pytest.fixture(autouse=True)
def relative_path_base(tmp_path: Path) -> Iterator[Path]:
    set_relative_path_base(tmp_path)
    yield tmp_path
    set_relative_path_base(None)


@pytest.fixture
def db_file(relative_path_base: Path) -> Path:
    path = relative_path_base / DBPPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def make_db(path: Path, sql: str, rows: list[tuple] | None = None) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(sql)
        if rows:
            table = "deerrecord" if "deerrecord" in sql else "deer_record"
            conn.executemany(f"insert into {table} values (?, ?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def schema_of(path: Path) -> tuple[set[str], set[str]]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "select type, name from sqlite_master where name not like 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {n for t, n in rows if t == "table"}, {n for t, n in rows if t == "index"}


def rows_of(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return sorted(conn.execute("select * from deer_record").fetchall())
    finally:
        conn.close()


async def startup_and_close(helper: SqliteDatabaseHelper) -> MigrationResult:
    results: list[MigrationResult] = []
    await helper.startup(prepare=lambda c: results.append(migrate(c)))
    await helper.close()
    return results[0]


def new_helper() -> SqliteDatabaseHelper:
    return SqliteDatabaseHelper(DBPPATH, metadata=deer_metadata)


@pytest.mark.asyncio
async def test_fresh_database_is_created_with_indexes(db_file: Path) -> None:
    assert await startup_and_close(new_helper()) is MigrationResult.FRESH
    assert schema_of(db_file) == ({"deer_record"}, REQUIRED_INDEX_NAMES)


@pytest.mark.asyncio
async def test_legacy_table_is_renamed_and_keeps_all_rows(db_file: Path) -> None:
    make_db(db_file, LEGACY_TABLE_SQL, LEGACY_ROWS)

    assert await startup_and_close(new_helper()) is MigrationResult.RENAMED_LEGACY
    assert schema_of(db_file) == ({"deer_record"}, REQUIRED_INDEX_NAMES)
    assert rows_of(db_file) == sorted(LEGACY_ROWS)


@pytest.mark.asyncio
async def test_missing_indexes_are_backfilled(db_file: Path) -> None:
    make_db(db_file, UNINDEXED_TABLE_SQL, LEGACY_ROWS)

    assert await startup_and_close(new_helper()) is MigrationResult.INDEXES_ADDED
    assert schema_of(db_file) == ({"deer_record"}, REQUIRED_INDEX_NAMES)
    assert rows_of(db_file) == sorted(LEGACY_ROWS)


@pytest.mark.asyncio
async def test_second_run_is_a_no_op(db_file: Path) -> None:
    make_db(db_file, LEGACY_TABLE_SQL, LEGACY_ROWS)
    await startup_and_close(new_helper())

    assert await startup_and_close(new_helper()) is MigrationResult.UP_TO_DATE
    assert rows_of(db_file) == sorted(LEGACY_ROWS)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sql", "match"),
    [
        (ANCIENT_TABLE_SQL, "缺少列"),
        (LEGACY_TABLE_SQL + UNINDEXED_TABLE_SQL, "同时存在"),
    ],
    ids=["missing-columns", "both-tables"],
)
async def test_unrecognized_schema_fails_and_leaves_database_untouched(
    db_file: Path, sql: str, match: str
) -> None:
    make_db(db_file, sql)
    before = schema_of(db_file)
    helper = new_helper()

    with pytest.raises(MigrationError, match=match):
        await helper.startup(prepare=migrate)
    with pytest.raises(StorageStartupError):
        await helper.wait_until_initialized(timeout=1)
    await helper.close()

    assert schema_of(db_file) == before


@pytest.mark.asyncio
async def test_migrated_legacy_data_is_queryable(db_file: Path) -> None:
    make_db(db_file, LEGACY_TABLE_SQL, LEGACY_ROWS)

    await deerdbcore.startup(prepare=migrate)
    try:
        # 旧库的 id 是 uuid4 的 32 位 hex, 新代码按 uuid.UUID 读写, 二者应当兼容
        recent = await query(uid=10086, gid=10010, time_range=(0, time.time()))
        assert sorted(c for _, c in recent) == [1, 3]

        await record(uid=10086, gid=10010, combo=2, ts=time.time())
        recent = await query(uid=10086, gid=10010, time_range=(0, time.time()))
        assert sorted(c for _, c in recent) == [1, 2, 3]
    finally:
        await deerdbcore.close()
