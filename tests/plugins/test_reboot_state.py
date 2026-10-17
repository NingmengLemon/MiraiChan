"""重启前后状态快照与对比。"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "packages" / "plugins"
if str(PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_ROOT))

from mbplugin_rebootable.state import (
    diff,
    find_repo_root,
    plugin_versions,
    read_commit,
    snapshot,
)


def _bot(plugins: dict[str, str]) -> SimpleNamespace:
    """假 bot: get_plugins 返回名字, _plugins 映射里带 planner.version"""
    return SimpleNamespace(
        get_plugins=lambda: list(plugins),
        _plugins={
            name: SimpleNamespace(planner=SimpleNamespace(version=version))
            for name, version in plugins.items()
        },
    )


def test_plugin_versions_reads_the_planner_version() -> None:
    assert plugin_versions(_bot({"a": "1.0.0", "b": "2.1.0"})) == {
        "a": "1.0.0",
        "b": "2.1.0",
    }


def test_plugin_versions_survives_a_missing_planner() -> None:
    bot = SimpleNamespace(get_plugins=lambda: ["a"], _plugins={"a": object()})
    assert plugin_versions(bot) == {"a": "?"}


def test_find_repo_root_walks_up(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    nested = root / "packages" / "plugins" / "p"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == root
    assert find_repo_root(tmp_path) is None


def test_read_commit_uses_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    # 没有 git 工程时返回 None, 不抛异常
    assert read_commit(repo) is None
    assert read_commit(None) is None


def test_read_commit_on_a_real_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com",
                "PATH": "/usr/bin:/bin:/usr/local/bin",
            },
        )

    try:
        git("init", "-q")
    except (OSError, subprocess.SubprocessError):
        return  # 没装 git 就跳过
    (repo / "a.txt").write_text("x", encoding="utf-8")
    git("add", "a.txt")
    git("commit", "-q", "-m", "init")
    commit = read_commit(repo)
    assert commit is not None
    assert len(commit) >= 7


def test_diff_reports_commit_plugin_add_remove_and_version() -> None:
    before = {
        "commit": "abc1234",
        "plugins": {"a": "1.0.0", "b": "1.0.0", "c": "0.9.0"},
    }
    after = {
        "commit": "def5678",
        "plugins": {"a": "1.0.0", "b": "1.1.0", "d": "1.0.0"},
    }
    lines = diff(before, after)
    assert "代码提交: abc1234 → def5678" in lines
    assert "新增插件: d" in lines
    assert "移除插件: c" in lines
    assert "插件版本: b 1.0.0 → 1.1.0" in lines


def test_diff_without_changes_says_so() -> None:
    state = {"commit": "abc1234", "plugins": {"a": "1.0.0"}}
    assert diff(state, state) == ["插件与代码提交都没有变化"]


def test_diff_with_an_old_reboot_info_skips_the_comparison() -> None:
    after = {"commit": "abc1234", "plugins": {"a": "1.0.0"}}
    assert diff(None, after) == ["重启前的状态没有记录, 跳过对比"]
    assert diff({}, after) == ["重启前的状态没有记录, 跳过对比"]


def test_snapshot_collects_commit_and_plugins(tmp_path: Path) -> None:
    state = snapshot(_bot({"a": "1.0.0"}), root=tmp_path)
    assert state["plugins"] == {"a": "1.0.0"}
    assert set(state) == {"commit", "plugins"}
