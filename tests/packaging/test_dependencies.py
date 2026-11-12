"""包内 import 的 workspace 依赖必须写进该包的 pyproject."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_PREFIXES = ("lemony_", "mbplugin_")
_DEP_NAME = re.compile(r"^[A-Za-z0-9_.-]+")


def _normalized(name: str) -> str:
    return name.lower().replace("-", "_")


def _pyprojects() -> list[Path]:
    return [
        path
        for path in sorted((REPO_ROOT / "packages").glob("**/pyproject.toml"))
        if "_to_be_migrated" not in path.parts
    ]


def _declared(path: Path) -> set[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    dependencies = data.get("project", {}).get("dependencies", [])
    names: set[str] = set()
    for dependency in dependencies:
        match = _DEP_NAME.match(dependency)
        if match is not None:
            names.add(_normalized(match.group()))
    return names


def _imported(path: Path) -> set[str]:
    names: set[str] = set()
    for source in path.rglob("*.py"):
        if any(part in {"tests", "__pycache__"} for part in source.parts):
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module is not None
            ):
                names.add(node.module.split(".", 1)[0])
    return {name for name in names if name.startswith(WORKSPACE_PREFIXES)}


@pytest.mark.parametrize("pyproject", _pyprojects(), ids=lambda path: path.parent.name)
def test_internal_imports_are_declared(pyproject: Path) -> None:
    package_dir = pyproject.parent
    source_dir = package_dir / "src"
    scan_dir = source_dir if source_dir.is_dir() else package_dir
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project_name = _normalized(data["project"]["name"])

    missing = _imported(scan_dir) - _declared(pyproject) - {project_name}
    assert not missing, (
        f"{pyproject.relative_to(REPO_ROOT)} 导入但未声明 workspace 依赖: "
        + ", ".join(sorted(missing))
    )
