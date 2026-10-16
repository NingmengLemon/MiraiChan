"""插件帮助信息的注册表.

各插件在模块级注册自己的指令说明, 帮助插件 (mbplugin_helper) 统一展示::

    from lemony_utils.help import Command, register_help

    register_help(
        "quote",
        title="引用图",
        summary="把群消息画成图片",
        commands=[
            Command(".q", "回复一条消息, 生成名言卡片"),
            Command(".qdel", "回复 bot 发出的引用图, 删除存档", admin_only=True),
        ],
    )

注册表与 bot 无关, 不依赖 melobot; 同一个 key 重复注册时后者覆盖前者, 插件热重载不会产生重复条目.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterable
from dataclasses import dataclass, field

__all__ = [
    "Command",
    "PluginHelp",
    "all_helps",
    "find_help",
    "register_help",
    "unregister_help",
]


@dataclass(frozen=True, slots=True)
class Command:
    usage: str
    """指令写法, 例如 ``.预警 设置 <项> <值>``"""
    desc: str = ""
    """说明, 可以多行"""
    admin_only: bool = False
    """仅 bot 管理员 (owner / admin) 可用"""

    def __post_init__(self) -> None:
        if not self.usage.strip():
            raise ValueError("指令写法不能为空")
        object.__setattr__(self, "usage", self.usage.strip())
        object.__setattr__(self, "desc", textwrap.dedent(self.desc).strip())


@dataclass(frozen=True, slots=True)
class PluginHelp:
    key: str
    """唯一标识, 用于 ``.help <key>`` 查询, 建议与插件的 PLUGIN_IDENTIFIER 一致"""
    title: str
    summary: str = ""
    commands: tuple[Command, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)
    """``.help`` 查询时额外接受的名字"""

    def names(self) -> set[str]:
        return {n.casefold() for n in (self.key, self.title, *self.aliases)}

    def render(self) -> str:
        """纯文本, 一个插件一段"""
        lines = [f"【{self.title}】"]
        if self.summary:
            lines.append(self.summary)
        for cmd in self.commands:
            mark = " (管理员)" if cmd.admin_only else ""
            lines.append(f"\n{cmd.usage}{mark}")
            lines.extend(f"  {line}" for line in cmd.desc.splitlines() if line.strip())
        return "\n".join(lines)


_registry: dict[str, PluginHelp] = {}


def register_help(
    key: str,
    *,
    title: str,
    summary: str = "",
    commands: Iterable[Command] = (),
    aliases: Iterable[str] = (),
) -> PluginHelp:
    key = key.strip()
    if not key or not title.strip():
        raise ValueError("key 与 title 不能为空")
    entry = PluginHelp(
        key=key,
        title=title.strip(),
        summary=textwrap.dedent(summary).strip(),
        commands=tuple(commands),
        aliases=tuple(a.strip() for a in aliases if a.strip()),
    )
    # 覆盖时保持原来的位置, 展示顺序不随重载变化
    _registry[key] = entry
    return entry


def unregister_help(key: str) -> bool:
    return _registry.pop(key, None) is not None


def all_helps() -> list[PluginHelp]:
    """按注册顺序"""
    return list(_registry.values())


def find_help(name: str) -> PluginHelp | None:
    """按 key / 标题 / 别名查找, 不区分大小写"""
    needle = name.strip().casefold()
    return next((h for h in _registry.values() if needle in h.names()), None)


def _reset_for_testing() -> None:
    _registry.clear()
