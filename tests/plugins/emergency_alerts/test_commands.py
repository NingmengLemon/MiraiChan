"""``.预警`` 指令."""

from __future__ import annotations

import pytest
from mbplugin_emergency_alerts.commands import HELP, CommandError, execute
from mbplugin_emergency_alerts.subscription import SubscriptionStore

GROUP = ("group", 20000)


def run(store, *tokens, can_manage=True, target=GROUP):
    return execute(store, target, list(tokens), can_manage=can_manage)


def test_no_args_shows_help():
    assert run(SubscriptionStore()).reply == HELP


def test_subscribe_with_defaults():
    store = SubscriptionStore()
    res = run(store, "订阅")
    assert res.changed
    sub = store.get(GROUP)
    assert sub is not None and sub.enabled and sub.target == GROUP


def test_pause_keeps_the_conditions_and_resume_restores_them():
    store = SubscriptionStore()
    run(store, "设置", "地区", "四川", "云南")
    run(store, "暂停")
    sub = store.get(GROUP)
    assert sub is not None and not sub.enabled and sub.regions == ["四川", "云南"]
    run(store, "订阅")
    sub = store.get(GROUP)
    assert sub is not None and sub.enabled and sub.regions == ["四川", "云南"]


def test_unsubscribe():
    store = SubscriptionStore()
    run(store, "订阅")
    assert run(store, "退订").changed
    assert store.get(GROUP) is None


@pytest.mark.parametrize(
    ("tokens", "field", "expected"),
    [
        (("种类", "速报"), "kinds", ["report"]),
        (("种类", "全部"), "kinds", ["eew", "report"]),
        (("来源", "cenc_eew", "JMA_EEW"), "sources", ["cenc_eew", "jma_eew"]),
        (("来源", "全部"), "sources", []),
        (("地区", "不限"), "regions", []),
        (("震级", "4.5"), "min_magnitude", 4.5),
        (("烈度", "6"), "min_intensity", 6.0),
        (("烈度", "不限"), "min_intensity", None),
        (("震度", "5-"), "min_shindo", "5-"),
        (("更新", "首报"), "updates", "first"),
    ],
)
def test_set_fields(tokens, field, expected):
    store = SubscriptionStore()
    res = run(store, "设置", *tokens)
    assert res.changed
    assert getattr(store.get(GROUP), field) == expected


@pytest.mark.parametrize(
    "tokens",
    [
        ("设置",),
        ("设置", "颜色", "红"),
        ("设置", "震级"),
        ("设置", "震级", "大"),
        ("设置", "震级", "12"),
        ("设置", "来源", "nope"),
        ("设置", "震度", "9"),
        ("设置", "更新", "偶尔"),
        ("暂停",),
        ("乱来",),
    ],
)
def test_invalid_commands_raise_and_change_nothing(tokens):
    store = SubscriptionStore()
    with pytest.raises(CommandError):
        run(store, *tokens)
    assert store.subscriptions == []


def test_members_cannot_change_a_group_subscription():
    store = SubscriptionStore()
    with pytest.raises(CommandError):
        run(store, "订阅", can_manage=False)
    assert store.subscriptions == []


def test_anyone_can_read_status_and_sources():
    store = SubscriptionStore()
    assert "尚未订阅" in run(store, "状态", can_manage=False).reply
    assert "cenc_eew" in run(store, "来源", can_manage=False).reply


def test_test_command_requests_a_test_push():
    res = run(SubscriptionStore(), "测试")
    assert res.send_test and not res.changed
