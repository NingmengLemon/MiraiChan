from pathlib import Path

import pytest
from lemony_storage_helper.database.sqlite import (
    get_relative_path_base,
    set_relative_path_base,
)
from lemony_storage_helper.files import (
    DataRootNotSetError,
    configured_data_path,
    data_path,
    get_data_root,
    is_data_root_set,
    set_data_root,
)


@pytest.fixture(autouse=True)
def _reset():
    set_data_root(None)
    set_relative_path_base(None)
    yield
    set_data_root(None)
    set_relative_path_base(None)


def test_unset_root_raises() -> None:
    assert not is_data_root_set()
    with pytest.raises(DataRootNotSetError):
        get_data_root()
    with pytest.raises(DataRootNotSetError):
        data_path("x")


def test_data_path_resolves_under_root(tmp_path: Path) -> None:
    set_data_root(tmp_path)
    assert data_path("avatars", "1.png") == tmp_path.resolve() / "avatars" / "1.png"
    assert data_path("a/../b") == tmp_path.resolve() / "b"
    assert data_path() == tmp_path.resolve()


def test_data_path_mkdir_parent(tmp_path: Path) -> None:
    set_data_root(tmp_path)
    p = data_path("deep", "dir", "f.txt", mkdir_parent=True)
    assert p.parent.is_dir()
    assert not p.exists()


@pytest.mark.parametrize("bad", ["..", "../x", "a/../../x", "/abs", "C:/abs", "C:rel"])
def test_data_path_rejects_escape(tmp_path: Path, bad: str) -> None:
    set_data_root(tmp_path / "root")
    with pytest.raises(ValueError):
        data_path(bad)


def test_configured_data_path(tmp_path: Path) -> None:
    set_data_root(tmp_path)
    root = tmp_path.resolve()
    # 旧配置以项目根为基准写的 data/xxx 与新写法指向同一个文件
    assert configured_data_path("data/reboot_info.json") == root / "reboot_info.json"
    assert configured_data_path("reboot_info.json") == root / "reboot_info.json"
    absolute = (tmp_path / "elsewhere" / "r.json").resolve()
    assert configured_data_path(str(absolute)) == absolute
    with pytest.raises(ValueError):
        configured_data_path("../outside.json")


def test_sqlite_base_falls_back_to_data_root(tmp_path: Path) -> None:
    assert get_relative_path_base() is None
    set_data_root(tmp_path)
    assert get_relative_path_base() == tmp_path.resolve()
    # 单独设置的数据库基准优先
    other = tmp_path / "db"
    set_relative_path_base(other)
    assert get_relative_path_base() == other.resolve()
