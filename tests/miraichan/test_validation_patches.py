"""melobot OneBot 兼容补丁的回归测试."""

from melobot.protocols.onebot.v11.adapter import echo as echo_module
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
