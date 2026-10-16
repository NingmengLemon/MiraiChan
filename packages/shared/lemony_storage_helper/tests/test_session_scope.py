"""会话作用域: 读过数据之后再写入时, 必须提交才能落库。

背景: 会话一旦执行过读取, SQLAlchemy 会自动开启事务, 之后的 auto_begin 只加
savepoint; 若没人提交外层事务, 退出时写入会静默回滚。recorder 的媒体下载 worker
曾经因此把每一条状态更新都丢掉, 无限重复处理同一批来源。
"""

from pathlib import Path

import pytest
from lemony_storage_helper.database.sqlite import SqliteDatabaseHelper
from lemony_storage_helper.database.utils import auto_begin
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select


def make_metadata() -> tuple[MetaData, Table]:
    metadata = MetaData()
    table = Table(
        "item",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    return metadata, table


async def ids(helper: SqliteDatabaseHelper, table: Table) -> list[int]:
    async with helper.engine.connect() as conn:
        return list(
            (await conn.execute(select(table.c.id).order_by(table.c.id))).scalars()
        )


@pytest.mark.asyncio
async def test_session_scope_commits_after_a_read(tmp_path: Path) -> None:
    metadata, table = make_metadata()
    helper = SqliteDatabaseHelper("s.db", metadata, relative_path_base=tmp_path)
    await helper.startup()
    try:
        async with helper.session_scope(style="sqlalchemy") as session:
            await session.execute(select(table))  # 先读: 触发 autobegin
            async with auto_begin(session):
                await session.execute(insert(table).values(id=1, name="a"))
        assert await ids(helper, table) == [1]
    finally:
        await helper.close()


@pytest.mark.asyncio
async def test_session_scope_rolls_back_on_error(tmp_path: Path) -> None:
    metadata, table = make_metadata()
    helper = SqliteDatabaseHelper("s.db", metadata, relative_path_base=tmp_path)
    await helper.startup()
    try:
        with pytest.raises(RuntimeError):
            async with helper.session_scope(style="sqlalchemy") as session:
                # 先读: 此时写入落在会话自己的事务里, 尚未提交
                await session.execute(select(table))
                async with auto_begin(session):
                    await session.execute(insert(table).values(id=1, name="a"))
                raise RuntimeError("boom")
        assert await ids(helper, table) == []

        # 对照: 没有先读时, auto_begin 自己开根事务并立即提交, 出错也撤不回来
        with pytest.raises(RuntimeError):
            async with helper.session_scope(style="sqlalchemy") as session:
                async with auto_begin(session):
                    await session.execute(insert(table).values(id=2, name="b"))
                raise RuntimeError("boom")
        assert await ids(helper, table) == [2]
    finally:
        await helper.close()


@pytest.mark.asyncio
async def test_bare_session_does_not_commit_after_a_read(tmp_path: Path) -> None:
    """记录既有行为: 直接用 get_session 当上下文管理器时, 先读后写不会落库。

    这不是期望的用法, 而是 API 契约 (退出时只关闭)。需要写入请用 session_scope;
    若将来把 get_session 改成退出即提交, 这个测试应当一起改掉。
    """
    metadata, table = make_metadata()
    helper = SqliteDatabaseHelper("s.db", metadata, relative_path_base=tmp_path)
    await helper.startup()
    try:
        async with helper.get_session(style="sqlalchemy") as session:
            await session.execute(select(table))
            async with auto_begin(session):
                await session.execute(insert(table).values(id=1, name="a"))
        assert await ids(helper, table) == []

        # 直接写 (没有先读) 时 auto_begin 开的是根事务, 会提交
        async with (
            helper.get_session(style="sqlalchemy") as session,
            auto_begin(session),
        ):
            await session.execute(insert(table).values(id=2, name="b"))
        assert await ids(helper, table) == [2]
    finally:
        await helper.close()
