"""构建全部 workspace 成员, 确认 sdist 与 wheel 都能产出.

`uv build --all-packages` 是 packaging 元数据的最终闸门: 缺 `[build-system]`、
包发现配置或 README 都会在这里失败。脚本不保留产物, 退出码非 0 即失败。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _members() -> list[Path]:
    dirs = [ROOT / "packages" / "miraichan"]
    dirs += sorted((ROOT / "packages" / "shared").glob("*"))
    dirs += sorted((ROOT / "packages" / "plugins").glob("mbplugin_*"))
    return [path for path in dirs if (path / "pyproject.toml").is_file()]


def main() -> int:
    members = _members()
    with tempfile.TemporaryDirectory(prefix="miraichan-build-") as tmp:
        out = Path(tmp)
        result = subprocess.run(
            ["uv", "build", "--all-packages", "--out-dir", str(out)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            print(result.stdout[-4000:], file=sys.stderr)
            print(result.stderr[-4000:], file=sys.stderr)
            print("uv build --all-packages 失败", file=sys.stderr)
            return result.returncode or 1

        wheels = sorted(out.glob("*.whl"))
        sdists = sorted(out.glob("*.tar.gz"))
        expected = len(members)
        if len(wheels) != expected or len(sdists) != expected:
            print(
                f"期望 {expected} 个 wheel 与 sdist, 实际 {len(wheels)} / {len(sdists)}",
                file=sys.stderr,
            )
            return 1

        names = set()
        for member in members:
            data = tomllib.loads(
                (member / "pyproject.toml").read_text(encoding="utf-8")
            )
            names.add(data["project"]["name"])
        normalized = {re.sub(r"[-_.]+", "_", name).lower() for name in names}
        wheel_names = {wheel.name.split("-")[0].lower() for wheel in wheels}
        missing = normalized - wheel_names
        if missing:
            print(f"缺少 wheel: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
        print(
            f"构建通过: {len(members)} 个包, {len(wheels)} wheels, {len(sdists)} sdists"
        )
        print(f"包: {', '.join(sorted(names))}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
