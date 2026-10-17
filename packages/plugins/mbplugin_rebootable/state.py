"""重启前后的状态快照与对比。

重启前把当时的状态写进 ``reboot_info.json``, 重启后拿新状态和它比一比, 报告插件的
增减、插件版本与代码提交的变化。这个模块只做记录与比较, 不碰 melobot 的运行时。
"""

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

__all__ = [
    "StateSnapshot",
    "diff",
    "find_repo_root",
    "plugin_versions",
    "read_commit",
    "snapshot",
]


class StateSnapshot(TypedDict, total=False):
    """重启前记下的状态; 两个键都可能缺 (例如不是 git 仓库)"""

    commit: str | None
    plugins: dict[str, str]


def find_repo_root(start: str | Path) -> Path | None:
    """从 ``start`` 往上找第一个含 ``.git`` 的目录"""
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def read_commit(root: str | Path | None) -> str | None:
    """代码提交的短哈希; 不是 git 仓库、没装 git、命令超时都返回 ``None``"""
    if root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def plugin_versions(bot: Any) -> dict[str, str]:
    """插件名 -> 版本号。

    melobot 只公开了插件名 (``bot.get_plugins()``), 版本得从它的内部映射里取;
    取不到的记成 ``"?"``, 不让对比功能把启动搞挂。
    """
    stored: Mapping[str, Any] = getattr(bot, "_plugins", {})
    versions: dict[str, str] = {}
    for name in bot.get_plugins():
        planner = getattr(stored.get(name), "planner", None)
        version = getattr(planner, "version", None)
        versions[name] = "?" if version is None else str(version)
    return versions


def snapshot(bot: Any, *, root: str | Path | None) -> StateSnapshot:
    """当前状态快照: 代码提交 + 插件版本"""
    return {"commit": read_commit(root), "plugins": plugin_versions(bot)}


def diff(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> list[str]:
    """把两次快照的差异变成几行中文; 没有区别时返回一句说明"""
    if not before:
        return ["重启前的状态没有记录, 跳过对比"]
    lines: list[str] = []
    before_commit = before.get("commit")
    after_commit = after.get("commit")
    if before_commit != after_commit:
        lines.append(f"代码提交: {before_commit or '未知'} → {after_commit or '未知'}")
    before_plugins: Mapping[str, str] = before.get("plugins") or {}
    after_plugins: Mapping[str, str] = after.get("plugins") or {}
    added = sorted(set(after_plugins) - set(before_plugins))
    removed = sorted(set(before_plugins) - set(after_plugins))
    changed = sorted(
        name
        for name in set(before_plugins) & set(after_plugins)
        if before_plugins[name] != after_plugins[name]
    )
    if added:
        lines.append("新增插件: " + ", ".join(added))
    if removed:
        lines.append("移除插件: " + ", ".join(removed))
    if changed:
        lines.append(
            "插件版本: "
            + "; ".join(
                f"{name} {before_plugins[name]} → {after_plugins[name]}"
                for name in changed
            )
        )
    return lines or ["插件与代码提交都没有变化"]
