"""凭据存储: 环境变量优先、文件次之、权限检查。"""

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from lemony_settings.credentials import (
    CredentialsFileError,
    ensure_credentials_file,
    env_name,
    get_secret,
    load_credentials,
    require_secret,
    set_credentials_path,
    warn_if_insecure,
)

KEY = "websocket.access_token"
ENV = env_name(KEY)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(ENV, raising=False)
    set_credentials_path(None)
    yield
    set_credentials_path(None)
    monkeypatch.delenv(ENV, raising=False)


def _write(path: Path, data: dict[str, str]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_env_name_normalizes_the_key() -> None:
    assert env_name("websocket.access_token") == "MIRAICHAN_WEBSOCKET_ACCESS_TOKEN"
    assert env_name("quote.api-key", prefix="X") == "X_QUOTE_API_KEY"
    assert env_name("a.b", prefix="") == "A_B"


def test_file_value_is_read_and_cached_until_it_changes(tmp_path: Path) -> None:
    path = _write(tmp_path / "credentials.json", {KEY: "from-file"})
    set_credentials_path(path)
    assert get_secret(KEY) == "from-file"
    assert load_credentials() == {KEY: "from-file"}

    # 外部改写后缓存失效, 不需要重启进程
    _write(path, {KEY: "rewritten"})
    os.utime(path, (1, 1))  # 保证 mtime/size 与上次不同
    assert get_secret(KEY) == "rewritten"


def test_env_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_credentials_path(_write(tmp_path / "credentials.json", {KEY: "from-file"}))
    monkeypatch.setenv(ENV, "from-env")
    assert get_secret(KEY) == "from-env"


def test_empty_values_count_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_credentials_path(_write(tmp_path / "credentials.json", {KEY: ""}))
    assert get_secret(KEY) is None
    monkeypatch.setenv(ENV, "")
    assert get_secret(KEY) is None


def test_missing_path_or_file_reads_as_empty(tmp_path: Path) -> None:
    assert get_secret(KEY) is None
    set_credentials_path(tmp_path / "nope.json")
    assert get_secret(KEY) is None
    with pytest.raises(KeyError):
        require_secret(KEY)


def test_broken_file_reports_which_file(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("{not json", encoding="utf-8")
    set_credentials_path(path)
    with pytest.raises(CredentialsFileError):
        get_secret(KEY)

    _write(path, {"k": 1})  # ty: ignore[invalid-argument-type]
    with pytest.raises(CredentialsFileError):
        load_credentials()


def test_ensure_creates_the_file_with_owner_only_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sub" / "credentials.json"
    set_credentials_path(path)
    created = ensure_credentials_file(template={KEY: ""})
    assert created == path
    assert json.loads(path.read_text(encoding="utf-8")) == {KEY: ""}
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    # 已存在时不覆盖内容
    _write(path, {KEY: "kept"})
    ensure_credentials_file()
    assert json.loads(path.read_text(encoding="utf-8")) == {KEY: "kept"}


def test_loose_permissions_are_reported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path / "credentials.json", {KEY: "x"})
    set_credentials_path(path)
    if os.name == "nt":
        assert warn_if_insecure() is False
        pytest.skip("Windows 不看 mode 位")
    path.chmod(0o644)
    with caplog.at_level("WARNING"):
        assert warn_if_insecure() is True
    assert any("chmod 600" in record.message for record in caplog.records)

    path.chmod(0o600)
    with caplog.at_level("WARNING"):
        assert warn_if_insecure() is False
