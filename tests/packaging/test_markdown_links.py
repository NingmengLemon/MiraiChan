"""仓库内 Markdown 的相对链接必须指向真实文件."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_REF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)")
_INLINE_CODE = re.compile(r"`[^`]*`")


def _tracked_markdown() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def _targets(text: str) -> list[tuple[int, str]]:
    """提取 inline 与 reference-style 的本地目标; 不校验锚点是否存在."""
    found: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        clean = _INLINE_CODE.sub("", line)
        for match in _LINK.finditer(clean):
            raw = match.group(1).strip()
            if raw.startswith("<") and raw.endswith(">"):
                raw = raw[1:-1]
            else:
                raw = raw.split(maxsplit=1)[0]
            found.append((lineno, raw))
        if match := _REF.match(clean):
            found.append((lineno, match.group(1)))
    return found


def _is_local(path: str) -> bool:
    if not path or path.startswith(("#", "/")):
        return False
    return not path.startswith(("http://", "https://", "mailto:", "tel:", "data:"))


@pytest.mark.parametrize(
    "path", _tracked_markdown(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_markdown_local_links_exist(path: Path) -> None:
    missing: list[str] = []
    for lineno, raw in _targets(path.read_text(encoding="utf-8")):
        if not _is_local(raw):
            continue
        target = unquote(raw.split("#", 1)[0].split("?", 1)[0])
        if not target:
            continue
        destination = (path.parent / target).resolve()
        if not destination.exists():
            missing.append(f"{path.relative_to(REPO_ROOT)}:{lineno} -> {raw}")
    assert not missing, "Markdown 相对链接指向不存在的路径:\n" + "\n".join(missing)
