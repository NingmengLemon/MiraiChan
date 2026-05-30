from pathlib import Path

import pytest
from sqlalchemy import MetaData

from lemony_storage_helper.database.sqlite import (
    SqliteDatabaseHelper,
    set_relative_path_base,
)


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


def test_sqlite_helper_rejects_empty_path() -> None:
    helper = SqliteDatabaseHelper("", MetaData())

    with pytest.raises(ValueError, match="cannot be empty string"):
        helper._resolve_dburl("")
