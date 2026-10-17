"""lemony_utils.help: 帮助信息注册表."""

from __future__ import annotations

import pytest
from lemony_utils import help as help_mod
from lemony_utils.help import (
    Command,
    all_helps,
    find_help,
    register_help,
    unregister_help,
)


@pytest.fixture(autouse=True)
def _clean():
    help_mod._reset_for_testing()
    yield
    help_mod._reset_for_testing()


def test_register_and_list_in_order():
    register_help("b", title="乙")
    register_help("a", title="甲")
    assert [h.key for h in all_helps()] == ["b", "a"]


def test_re_register_replaces_in_place():
    register_help("a", title="甲")
    register_help("b", title="乙")
    register_help("a", title="甲2")
    assert [(h.key, h.title) for h in all_helps()] == [("a", "甲2"), ("b", "乙")]


def test_find_by_key_title_or_alias_case_insensitive():
    register_help("quote", title="引用图", aliases=["q", "MQ"])
    for name in ("quote", "QUOTE", "引用图", "q", "mq"):
        found = find_help(name)
        assert found is not None and found.key == "quote", name
    assert find_help("nope") is None


def test_unregister():
    register_help("a", title="甲")
    assert unregister_help("a")
    assert not unregister_help("a")
    assert all_helps() == []


@pytest.mark.parametrize(("key", "title"), [("", "t"), ("k", " ")])
def test_rejects_empty_key_or_title(key, title):
    with pytest.raises(ValueError):
        register_help(key, title=title)


def test_command_rejects_empty_usage():
    with pytest.raises(ValueError):
        Command("  ")


def test_render_dedents_and_marks_admin_commands():
    entry = register_help(
        "x",
        title="示例",
        summary="一句话说明",
        commands=[
            Command(
                ".x <参数>",
                """
                第一行
                第二行
                """,
            ),
            Command(".x reset", "重置", admin_only=True),
        ],
    )
    assert entry.render() == (
        "【示例】\n一句话说明\n\n.x <参数>\n  第一行\n  第二行\n\n.x reset (管理员)\n  重置"
    )
