"""实现端扩展清单

清单本身是数据, 存在 ``resources/extensions.json``, 用 JSON Schema 约束形状; 这里只负责加载成
:class:`ExtensionSpec` 并提供查询。这样条目可以脱离 Python 编辑, 也方便外部工具或文档生成读取。

不是每个实现端都支持同一批扩展, 支持情况也随版本变化。``impls`` 只写有源码或实测证据的来源,
``notes`` 记录参数形状与还没核实完的传闻, 避免把"应该支持"写成事实。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal

__all__ = [
    "EXTENSIONS",
    "SPECS",
    "ExtensionSpec",
    "find",
    "for_impl",
    "load_entries",
]

ExtensionKind = Literal["action", "event", "segment"]

_KINDS = ("action", "event", "segment")


@dataclass(frozen=True, slots=True)
class ExtensionSpec:
    name: str
    kind: ExtensionKind
    summary: str
    impls: tuple[str, ...] = ()
    notes: str = ""
    source: str = ""

    def supported_by(self, impl: str) -> bool:
        return impl in self.impls


def _resource() -> Any:
    return files(__package__).joinpath("resources/extensions.json")


def load_entries(entries: list[dict[str, Any]]) -> tuple[ExtensionSpec, ...]:
    """把 JSON 条目转成 dataclass; 重名或 kind 非法时直接报错, 不静默覆盖"""
    specs: list[ExtensionSpec] = []
    seen: set[str] = set()
    for item in entries:
        name = str(item["name"])
        if name in seen:
            raise ValueError(f"扩展清单里有重复条目: {name}")
        seen.add(name)
        kind = item["kind"]
        if kind not in _KINDS:
            raise ValueError(f"{name} 的 kind 非法: {kind!r}")
        specs.append(
            ExtensionSpec(
                name=name,
                kind=kind,
                summary=str(item["summary"]),
                impls=tuple(str(impl) for impl in item.get("impls", ())),
                notes=str(item.get("notes", "")),
                source=str(item.get("source", "")),
            )
        )
    return tuple(specs)


def _load() -> tuple[ExtensionSpec, ...]:
    raw = json.loads(_resource().read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("extensions.json 顶层必须是数组")
    return load_entries(raw)


#: 全部收录条目, 顺序即 JSON 里的顺序
SPECS = _load()

#: 名称 -> 条目
EXTENSIONS: dict[str, ExtensionSpec] = {spec.name: spec for spec in SPECS}


def find(name: str) -> ExtensionSpec | None:
    return EXTENSIONS.get(name)


def for_impl(impl: str) -> tuple[ExtensionSpec, ...]:
    """某个实现端有证据支持的扩展"""
    return tuple(spec for spec in SPECS if spec.supported_by(impl))
