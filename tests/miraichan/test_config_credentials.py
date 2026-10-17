"""根配置的凭据覆盖: 凭据文件与环境变量取代 config.json 里的明文 access_token。"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from lemony_settings.credentials import set_credentials_path
from miraichan.config import (
    GlobalConfigModel,
    apply_credential_overrides,
    plaintext_token_present,
)

KEY = "websocket.access_token"
ENV = "MIRAICHAN_WEBSOCKET_ACCESS_TOKEN"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(ENV, raising=False)
    set_credentials_path(None)
    yield
    set_credentials_path(None)
    monkeypatch.delenv(ENV, raising=False)


def _token(cfg: GlobalConfigModel) -> str | None:
    return cfg.websocket.access_token.get_secret_value()


def test_credentials_file_fills_the_token(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({KEY: "from-file"}), encoding="utf-8")
    set_credentials_path(path)

    raw = {"websocket": {"type": "forward", "url": "ws://x:1"}, "plugins": ["p"]}
    cfg = GlobalConfigModel.model_validate(apply_credential_overrides(raw))
    assert _token(cfg) == "from-file"
    # 原始配置没有被就地改写
    assert "access_token" not in raw["websocket"]


def test_env_var_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({KEY: "from-file"}), encoding="utf-8")
    set_credentials_path(path)
    monkeypatch.setenv(ENV, "from-env")

    cfg = GlobalConfigModel.model_validate(
        apply_credential_overrides({"websocket": {"type": "forward"}})
    )
    assert _token(cfg) == "from-env"


def test_plaintext_config_token_still_works(tmp_path: Path) -> None:
    """迁移期: 没配凭据时照旧读 config.json 里的 token, 只是会提示挪走"""
    set_credentials_path(tmp_path / "none.json")
    raw = {"websocket": {"type": "forward", "access_token": "legacy"}}
    assert plaintext_token_present(raw)
    cfg = GlobalConfigModel.model_validate(apply_credential_overrides(raw))
    assert _token(cfg) == "legacy"


def test_no_token_at_all_is_fine(tmp_path: Path) -> None:
    set_credentials_path(tmp_path / "none.json")
    raw = {"websocket": {"type": "forward"}}
    assert not plaintext_token_present(raw)
    cfg = GlobalConfigModel.model_validate(apply_credential_overrides(raw))
    assert _token(cfg) is None
