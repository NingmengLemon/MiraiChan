"""melobot OneBot 兼容补丁的回归测试."""

from importlib.metadata import PackageNotFoundError

import pytest
from melobot.protocols.onebot.v11.adapter import echo as echo_module
from miraichan.validation_patches import ob11
from miraichan.validation_patches.ob11 import patch_forward_echo


def test_patch_forward_echo_keeps_raw_forward_data() -> None:
    original = echo_module.GetForwardMsgEcho
    try:
        patch_forward_echo()
        patched = echo_module.GetForwardMsgEcho
        assert patched is not original
        assert getattr(patched, "_forward_echo_raw", False)

        # 再次调用应保持幂等, 不叠加新的类
        patch_forward_echo()
        assert echo_module.GetForwardMsgEcho is patched

        raw = {
            "status": "ok",
            "retcode": 0,
            "data": {"messages": [{"type": "node", "data": {}}]},
            "action_type": "get_forward_msg",
        }
        echo = echo_module.Echo.resolve(raw)
        assert isinstance(echo, patched)
        assert echo.raw["data"] == {"messages": [{"type": "node", "data": {}}]}
    finally:
        echo_module.GetForwardMsgEcho = original


def test_unsupported_melobot_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ob11, "version", lambda _name: "3.6.0")
    with pytest.raises(RuntimeError, match=r"只支持 melobot 3\.5"):
        patch_forward_echo()


def test_missing_melobot_metadata_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_name: str) -> str:
        raise PackageNotFoundError("melobot")

    monkeypatch.setattr(ob11, "version", missing)
    with pytest.raises(RuntimeError, match="找不到 melobot"):
        patch_forward_echo()
