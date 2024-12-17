"""
*Blood covers the whole floor, screams echo, people are running away...*

*- All-Around Helper's Entry*

~~神金()~~
"""

import textwrap
from typing import NotRequired, TypedDict

from melobot.utils import singleton

__all__ = [
    "set_bot_name",
    "register",
    "export_markdown",
]


class CommandHelp(TypedDict):
    cmd: str
    text: NotRequired[str]


@singleton
class _Helper:
    def __init__(self):
        self._bot_name = "Bot"
        self._helps: dict[str, list[CommandHelp]] = {}

    def set_bot_name(self, name: str):
        self._bot_name = name

    def register(self, plugin_name: str, *commands: CommandHelp):
        if not plugin_name or plugin_name[0].isdigit():
            raise ValueError("无效的插件名称")
        if plugin_name not in self._helps:
            self._helps[plugin_name] = []
        self._helps[plugin_name].extend(
            [
                {
                    "cmd": c["cmd"].strip(),
                    "text": textwrap.dedent(c["text"]),
                }
                for c in commands
            ]
        )

    def markdown(self, plugin: str | None = None):
        lines = [
            f"# {self._bot_name} 的帮助信息！",
            # "\n*Powered by Little Helper*",
        ]
        initial_len = len(lines)
        for plugin_name, commands in self._helps.items():
            if plugin is not None and plugin.lower() != plugin_name.lower():
                continue
            lines.append(f"\n## {plugin_name}")
            for cmd in commands:
                lines.append(f"\n- `{cmd['cmd']}`")
                if text := cmd.get("text"):
                    lines.extend([f"    - {l.strip()}" for l in text.splitlines() if l])

        if len(lines) == initial_len:
            lines.append("暂时没有帮助信息w")
        return "\n".join(lines)


_helper = _Helper()


def set_bot_name(name: str):
    _helper.set_bot_name(name)


def register(plugin_name: str, /, *commands: CommandHelp):
    _helper.register(plugin_name, *commands)


def export_markdown(plugin: str | None = None):
    return _helper.markdown(plugin)
