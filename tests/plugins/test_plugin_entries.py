"""插件入口模块的结构约束

这些不是行为测试, 而是把踩过的坑做成闸门, 防止同类问题再回来。

``from __future__ import annotations`` 会让 handler 的参数注解变成字符串, melobot 用 beartype
解析签名时拿不到真正的类型, 插件在加载阶段就失败 (``Type hint 'MessageEvent' currently
unsupported``)。这个问题单元测试碰不到, 因为测试不会 import 入口模块 (那需要 bot 实例),
所以只能静态检查源码。同样的坑在 forward_strip 与 mikufans 上各踩过一次。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRY_FILES = sorted((REPO_ROOT / "packages" / "plugins").glob("*/__plugin__.py"))


def test_entry_modules_exist() -> None:
    assert len(ENTRY_FILES) >= 10


@pytest.mark.parametrize("path", ENTRY_FILES, ids=[p.parent.name for p in ENTRY_FILES])
def test_entry_module_does_not_postpone_annotations(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    offenders = [
        line for line in lines if line.strip() == "from __future__ import annotations"
    ]
    assert not offenders, (
        f"{path.parent.name}/__plugin__.py 不能使用 postponed annotations: "
        "handler 注解会变成字符串, melobot 的 beartype 无法解析, 插件加载即失败"
    )
