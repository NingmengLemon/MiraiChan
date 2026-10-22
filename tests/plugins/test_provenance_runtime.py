"""核验插件的运行期状态: 去重与冷却

入口模块需要 bot 实例, 测试导入不了, 所以这部分逻辑单独放一个模块测。
"""

from __future__ import annotations

from mbplugin_provenance.runtime import Cooldown, InFlight


def test_in_flight_rejects_same_user() -> None:
    guard = InFlight()
    assert guard.try_enter(1)
    assert not guard.try_enter(1)
    guard.leave(1)
    assert guard.try_enter(1)
    # 别的用户不受影响
    assert guard.try_enter(2)


def test_in_flight_membership() -> None:
    guard = InFlight()
    guard.try_enter(7)
    assert 7 in guard
    guard.leave(7)
    assert 7 not in guard
    # 重复 leave 不应该炸
    guard.leave(7)


def test_cooldown_remaining() -> None:
    cooldown = Cooldown(seconds=10.0)
    assert cooldown.remaining(1, now=100.0) == 0.0
    cooldown.touch(1, now=100.0)
    assert cooldown.remaining(1, now=103.0) == 7.0
    assert cooldown.remaining(1, now=115.0) == 0.0
    # 独立用户不共享冷却
    assert cooldown.remaining(2, now=103.0) == 0.0
