"""把帮助注册表渲染成转发消息的各个节点 (纯函数, 不依赖 bot)."""

from __future__ import annotations

from collections.abc import Sequence

from lemony_utils.help import PluginHelp

__all__ = ["overview_nodes", "plugin_nodes"]


def _index(helps: Sequence[PluginHelp], bot_name: str) -> str:
    lines = [f"{bot_name} 的帮助", "发送 .help <名称> 只看某一项", ""]
    for h in helps:
        tail = f": {h.summary.splitlines()[0]}" if h.summary else ""
        lines.append(f"· {h.title} ({h.key}){tail}")
    return "\n".join(lines)


def overview_nodes(helps: Sequence[PluginHelp], bot_name: str) -> list[str]:
    """首个节点是目录, 之后每个插件一个节点 (过长时由 ForwardBuilder 再拆)"""
    if not helps:
        return ["暂时没有帮助信息"]
    return [_index(helps, bot_name), *(h.render() for h in helps)]


def plugin_nodes(entry: PluginHelp) -> list[str]:
    """单个插件: 简介一个节点, 之后每条指令一个节点, 便于在客户端里分条阅读"""
    head = f"【{entry.title}】"
    if entry.summary:
        head += f"\n{entry.summary}"
    nodes = [head]
    for cmd in entry.commands:
        mark = " (管理员)" if cmd.admin_only else ""
        nodes.append(f"{cmd.usage}{mark}\n{cmd.desc}".rstrip())
    return nodes
