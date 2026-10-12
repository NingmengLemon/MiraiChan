"""mbplugin_checker_manager ID 约束解析的回归测试。

覆盖两类静默失效:

- 笔误的 ID 串 (如 ",") 曾经被解析成"匹配所有": 解析不出任何 ID 时旧实现返回 None,
  于是 ``.checker global add deny ,`` 落库成一条无条件拒绝规则, 权限范围被悄悄放大。
  现在必须显式报错。
- 命令按空白分词, ``.checker global add deny 123, 456`` 会传进 ``["123,", "456"]``,
  旧实现只取第一个分词, 456 被静默丢弃。

测试文件不能放在插件包目录里: pytest 会导入插件的 __init__.py 并查询 pytest_plugins 属性,
而 melobot 生成的 __getattr__ 在没有 bot 实例时会抛 BotError。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from mbplugin_checker_manager.parsing import (  # noqa: E402
    ConstraintParseError,
    ThisInPrivateChatError,
    join_id_tokens,
    parse_constrains,
)


class TestMatchAll:
    """省略参数与别名表示匹配所有."""

    @pytest.mark.parametrize("ids_str", [None, "all", "ALL", "none", "*", " * "])
    def test_returns_none(self, ids_str: str | None):
        assert parse_constrains(ids_str) is None

    def test_none_with_group_id(self):
        """群聊里省略 ids 同样是匹配所有, 与 group_id 无关."""
        assert parse_constrains(None, group_id=5000) is None


class TestValidInput:
    """正常 ID 串的解析结果."""

    def test_user_only(self):
        assert parse_constrains("1001") == [{"user_id": [1001]}]

    def test_user_and_group(self):
        assert parse_constrains("1001:5000") == [
            {"user_id": [1001], "group_id": [5000]}
        ]

    def test_multiple_constraints_are_or(self):
        assert parse_constrains("1001:5000,1002") == [
            {"user_id": [1001], "group_id": [5000]},
            {"user_id": [1002]},
        ]

    def test_whitespace_around_comma(self):
        assert parse_constrains("123, 456") == [
            {"user_id": [123]},
            {"user_id": [456]},
        ]

    def test_trailing_comma_tolerated(self):
        assert parse_constrains("1001,") == [{"user_id": [1001]}]

    def test_empty_group_is_user_only(self):
        """'1001:' 表示不限群组, 与 '1001' 等价."""
        assert parse_constrains("1001:") == [{"user_id": [1001]}]

    def test_this_expands_to_current_group(self):
        assert parse_constrains("this", group_id=5000) == [{"group_id": [5000]}]

    def test_this_among_others(self):
        assert parse_constrains("1001,this", group_id=5000) == [
            {"user_id": [1001]},
            {"group_id": [5000]},
        ]


class TestInvalidInput:
    """解析失败必须抛异常, 不能退化成 "匹配所有"."""

    @pytest.mark.parametrize(
        "ids_str",
        ["", "   ", ",", ",,", " , ", ", , ,"],
    )
    def test_empty_list_raises(self, ids_str: str):
        with pytest.raises(ConstraintParseError):
            parse_constrains(ids_str)

    @pytest.mark.parametrize("ids_str", ["abc", "1001:abc", "abc:5000", "1001 1002"])
    def test_bad_id_format_raises(self, ids_str: str):
        with pytest.raises(ConstraintParseError):
            parse_constrains(ids_str)

    def test_this_in_private_chat_raises(self):
        with pytest.raises(ThisInPrivateChatError):
            parse_constrains("this")

    @pytest.mark.parametrize(
        "ids_str", ["", "   ", ",", ",,", "abc", "1001:abc", "this"]
    )
    def test_never_falls_back_to_match_all(self, ids_str: str):
        """任何无法解析的输入都不得返回 None (None 等于无条件规则)."""
        with pytest.raises((ConstraintParseError, ThisInPrivateChatError)):
            parse_constrains(ids_str)


class TestJoinIdTokens:
    """命令分词被空白拆散后要能拼回去."""

    def test_single_token(self):
        assert join_id_tokens(["1001"]) == "1001"

    def test_split_on_space_after_comma(self):
        """'123, 456' 被切成 ['123,', '456'], 两个 ID 都要保留."""
        assert join_id_tokens(["123,", "456"]) == "123,456"
        assert parse_constrains(join_id_tokens(["123,", "456"])) == [
            {"user_id": [123]},
            {"user_id": [456]},
        ]

    def test_space_separated_without_comma(self):
        """'123 456' (漏写逗号) 也按两个 ID 处理, 而不是拼成一个错误的 ID."""
        assert parse_constrains(join_id_tokens(["123", "456"])) == [
            {"user_id": [123]},
            {"user_id": [456]},
        ]

    def test_standalone_commas_dropped(self):
        assert join_id_tokens([",", "456"]) == "456"
        assert join_id_tokens([","]) == ""

    def test_only_commas_raises_after_join(self):
        """'add deny ,' 的场景: 拼回空串, 解析报错而不是落成匹配所有."""
        with pytest.raises(ConstraintParseError):
            parse_constrains(join_id_tokens([",", ","]))
