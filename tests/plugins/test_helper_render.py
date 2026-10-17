"""mbplugin_helper 的帮助渲染 (不依赖 bot)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from lemony_utils.help import Command, PluginHelp
from mbplugin_helper.render import overview_nodes, plugin_nodes

QUOTE = PluginHelp(
    key="quote",
    title="引用图",
    summary="把群消息画成图片\n第二行不进目录",
    commands=(
        Command(".q", "名言卡片"),
        Command(".qdel", "删除存档", admin_only=True),
    ),
)
BARE = PluginHelp(key="bare", title="无说明")


def test_empty_registry():
    assert overview_nodes([], "Bot") == ["暂时没有帮助信息"]


def test_overview_is_an_index_then_one_node_per_plugin():
    nodes = overview_nodes([QUOTE, BARE], "Bot")
    assert len(nodes) == 3
    index = nodes[0]
    assert index.startswith("Bot 的帮助")
    assert "· 引用图 (quote): 把群消息画成图片" in index
    assert "第二行不进目录" not in index
    assert "· 无说明 (bare)" in index
    assert nodes[1] == QUOTE.render()


def test_single_plugin_is_split_per_command():
    assert plugin_nodes(QUOTE) == [
        "【引用图】\n把群消息画成图片\n第二行不进目录",
        ".q\n名言卡片",
        ".qdel (管理员)\n删除存档",
    ]


def test_command_without_description_has_no_trailing_newline():
    entry = PluginHelp(key="x", title="X", commands=(Command(".x"),))
    assert plugin_nodes(entry) == ["【X】", ".x"]
