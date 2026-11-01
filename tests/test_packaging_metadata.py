"""包元数据与插件版本的一致性检查."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = sorted(
    path
    for path in (REPO_ROOT / "packages").glob("**/pyproject.toml")
    if "_to_be_migrated" not in path.parts
)
PLUGIN_DIRS = sorted(
    path.parent
    for path in (REPO_ROOT / "packages" / "plugins").glob("*/pyproject.toml")
    if "_to_be_migrated" not in path.parts
)


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


@pytest.mark.parametrize("path", PACKAGE_FILES, ids=lambda p: str(p.parent))
def test_declared_readme_exists(path: Path) -> None:
    readme = _project(path).get("readme")
    if readme is not None:
        assert (path.parent / readme).is_file(), f"{path}: missing {readme}"


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=lambda p: p.name)
def test_plugin_version_matches_planner(plugin_dir: Path) -> None:
    pyproject = _project(plugin_dir / "pyproject.toml")
    entry = (plugin_dir / "__plugin__.py").read_text(encoding="utf-8")
    match = re.search(r"PluginPlanner\(\s*[\"']([^\"']+)", entry)
    assert match is not None, f"{plugin_dir}: PluginPlanner version not found"
    assert match.group(1) == pyproject["version"], f"{plugin_dir}: pyproject/planner"

    init = plugin_dir / "__init__.py"
    if init.is_file():
        init_match = re.search(
            r"^__version__\s*=\s*[\"']([^\"']+)", init.read_text(encoding="utf-8"), re.M
        )
        if init_match is not None:
            assert init_match.group(1) == pyproject["version"], (
                f"{plugin_dir}: pyproject/__init__"
            )
