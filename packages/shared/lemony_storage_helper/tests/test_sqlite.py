import asyncio
from pathlib import Path

import pytest
from lemony_storage_helper.database import StorageStartupError
from lemony_storage_helper.database.sqlite import (
    SqliteDatabaseHelper,
    set_relative_path_base,
)
from sqlalchemy import Column, Integer, MetaData, String, Table, func, insert, select


@pytest.fixture(autouse=True)
def reset_relative_path_base():
    set_relative_path_base(None)
    yield
    set_relative_path_base(None)


@pytest.mark.asyncio
async def test_sqlite_helper_supports_in_memory_database() -> None:
    helper = SqliteDatabaseHelper(None, MetaData())

    await helper.startup()
    try:
        assert helper.in_memory is True
    finally:
        await helper.close()


@pytest.mark.asyncio
async def test_sqlite_helper_resolves_relative_path_on_startup(tmp_path: Path) -> None:
    helper = SqliteDatabaseHelper("nested/test.db", MetaData(), relative_path_base=tmp_path)

    await helper.startup()
    try:
        assert helper.in_memory is False
        assert (tmp_path / "nested" / "test.db").is_file()
    finally:
        await helper.close()


@pytest.mark.asyncio
async def test_sqlite_helper_uses_late_bound_upper_relative_path_base(
    tmp_path: Path,
) -> None:
    helper = SqliteDatabaseHelper("late/test.db", MetaData())
    set_relative_path_base(tmp_path)

    await helper.startup()
    try:
        assert helper.in_memory is False
        assert (tmp_path / "late" / "test.db").is_file()
    finally:
        await helper.close()


def test_sqlite_helper_rejects_relative_path_without_base() -> None:
    helper = SqliteDatabaseHelper("missing-base.db", MetaData())

    with pytest.raises(ValueError, match="relative_path_base is required"):
        helper._resolve_dburl("missing-base.db")


def _counter_metadata() -> tuple[MetaData, Table]:
    metadata = MetaData()
    table = Table(
        "item",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    return metadata, table


async def _count(helper: SqliteDatabaseHelper, table: Table) -> int:
    async with helper.engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(table))).scalar_one()


@pytest.mark.asyncio
async def test_savepoint_after_select_is_rolled_back_with_outer_transaction(
    tmp_path: Path,
) -> None:
    # 回归: 驱动自行管理事务时, SELECT 后的 SAVEPOINT 落在事务外, RELEASE 即提交
    metadata, table = _counter_metadata()
    helper = SqliteDatabaseHelper("tx.db", metadata, relative_path_base=tmp_path)
    await helper.startup()
    try:
        async with helper.get_session(style="sqlalchemy") as session:
            async with session.begin() as outer:
                await session.execute(select(table))
                async with session.begin_nested():
                    await session.execute(insert(table).values(id=1, name="inner"))
                await session.execute(insert(table).values(id=2, name="outer"))
                await outer.rollback()
        assert await _count(helper, table) == 0
    finally:
        await helper.close()


@pytest.mark.asyncio
async def test_file_database_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    metadata, _ = _counter_metadata()
    helper = SqliteDatabaseHelper(
        "wal.db", metadata, relative_path_base=tmp_path, busy_timeout=3
    )
    await helper.startup()
    try:
        async with helper.engine.connect() as conn:
            mode = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
            fk = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
        assert (mode, timeout, fk) == ("wal", 3000, 1)
    finally:
        await helper.close()


@pytest.mark.asyncio
async def test_concurrent_writers_do_not_fail_with_database_locked(
    tmp_path: Path,
) -> None:
    metadata, table = _counter_metadata()
    helper = SqliteDatabaseHelper("busy.db", metadata, relative_path_base=tmp_path)
    await helper.startup()

    async def writer(i: int) -> None:
        async with helper.get_session(style="sqlalchemy") as session:
            async with session.begin():
                # 先读后写, 是 DEFERRED 事务下最容易撞 SQLITE_BUSY 的形态
                await session.execute(select(table).where(table.c.id == i))
                await asyncio.sleep(0.01)
                await session.execute(insert(table).values(id=i, name=f"w{i}"))

    try:
        await asyncio.gather(*(writer(i) for i in range(20)))
        assert await _count(helper, table) == 20
    finally:
        await helper.close()


@pytest.mark.asyncio
async def test_waiters_are_released_when_startup_fails(tmp_path: Path) -> None:
    # 回归: startup 失败后 wait_until_initialized 不能永久挂起
    metadata, _ = _counter_metadata()
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("")
    helper = SqliteDatabaseHelper(
        "not_a_dir/x.db", metadata, relative_path_base=tmp_path
    )
    waiter = asyncio.create_task(helper.wait_until_initialized(timeout=5))
    await asyncio.sleep(0)

    with pytest.raises(OSError):
        await helper.startup()
    with pytest.raises(StorageStartupError):
        await waiter
    assert helper.is_initialized() is False
    assert isinstance(helper.startup_failure, OSError)
    await helper.close()


def test_sqlite_helper_rejects_empty_path() -> None:
    helper = SqliteDatabaseHelper("", MetaData())

    with pytest.raises(ValueError, match="cannot be empty string"):
        helper._resolve_dburl("")
