"""订阅模型: 一个会话 (群聊或私聊) 一条订阅.

筛选维度:
- 种类: 地震预警 (eew) / 地震速报 (report)
- 数据源: 为空表示全部
- 地区: 关键词与震源地做子串匹配, 为空表示不限地区
- 严重程度: 最小震级, 以及可选的最小烈度 (中国源) / 最小震度 (日本源)

阈值只作用于报文里有的指标: 日本源没有中国烈度, ``min_intensity`` 不会因此把它们全挡掉;
同理 ``min_shindo`` 不影响中国源。
"""

from __future__ import annotations

from typing import Literal

from lemony_settings import BaseSettings
from pydantic import BaseModel, Field, field_validator

from .quake import Quake, QuakeKind, shindo_rank
from .sources.wolfx import SOURCES

__all__ = [
    "KIND_LABELS",
    "UPDATE_LABELS",
    "Subscription",
    "SubscriptionStore",
    "TargetKey",
    "TargetType",
    "UpdatePolicy",
]

type TargetType = Literal["group", "private"]
type TargetKey = tuple[TargetType, int]
type UpdatePolicy = Literal["first", "final", "all"]

KIND_LABELS: dict[QuakeKind, str] = {"eew": "地震预警", "report": "地震速报"}
ALL_KINDS: tuple[QuakeKind, ...] = ("eew", "report")
UPDATE_LABELS: dict[UpdatePolicy, str] = {
    "first": "只推首报",
    "final": "首报 + 最终报",
    "all": "每一报都推",
}


class Subscription(BaseModel):
    model_config = {"validate_assignment": True}

    target_type: TargetType
    target_id: int
    enabled: bool = True
    kinds: list[QuakeKind] = Field(default_factory=lambda: list(ALL_KINDS))
    sources: list[str] = Field(default_factory=list, description="为空表示全部数据源")
    regions: list[str] = Field(default_factory=list, description="为空表示不限地区")
    min_magnitude: float = Field(default=4.0, ge=0, le=10)
    min_intensity: float | None = Field(default=None, ge=0, le=12)
    min_shindo: str | None = None
    updates: UpdatePolicy = "final"

    @field_validator("sources")
    @classmethod
    def _known_sources(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in SOURCES]
        if unknown:
            raise ValueError(f"未知数据源: {', '.join(unknown)}")
        return list(dict.fromkeys(v))

    @field_validator("kinds")
    @classmethod
    def _non_empty_kinds(cls, v: list[QuakeKind]) -> list[QuakeKind]:
        if not v:
            raise ValueError("至少订阅一种信息")
        return list(dict.fromkeys(v))

    @field_validator("regions")
    @classmethod
    def _clean_regions(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(r.strip() for r in v if r.strip()))

    @field_validator("min_shindo")
    @classmethod
    def _valid_shindo(cls, v: str | None) -> str | None:
        if v is not None and shindo_rank(v) is None:
            raise ValueError(f"无法识别的震度: {v!r} (可用 1 2 3 4 5- 5+ 6- 6+ 7)")
        return v

    @property
    def target(self) -> TargetKey:
        return (self.target_type, self.target_id)

    def matches(self, quake: Quake) -> bool:
        """报文是否落在订阅范围内 (不考虑更新策略)"""
        if not self.enabled or quake.kind not in self.kinds:
            return False
        if self.sources and quake.source not in self.sources:
            return False
        if self.regions and not any(r in quake.region_text for r in self.regions):
            return False
        return self._severe_enough(quake)

    def _severe_enough(self, quake: Quake) -> bool:
        if quake.magnitude is not None and quake.magnitude < self.min_magnitude:
            return False
        if (
            self.min_intensity is not None
            and quake.intensity is not None
            and quake.intensity < self.min_intensity
        ):
            return False
        if self.min_shindo is not None:
            need, got = shindo_rank(self.min_shindo), shindo_rank(quake.shindo)
            if need is not None and got is not None and got < need:
                return False
        return True

    def describe(self) -> str:
        lines = [
            f"状态: {'开启' if self.enabled else '已暂停'}",
            f"种类: {'、'.join(KIND_LABELS[k] for k in self.kinds)}",
            f"数据源: {'全部' if not self.sources else '、'.join(SOURCES[s].name for s in self.sources)}",
            f"地区: {'不限' if not self.regions else '、'.join(self.regions)}",
            f"最小震级: M{self.min_magnitude:g}",
        ]
        if self.min_intensity is not None:
            lines.append(f"最小烈度 (中国源): {self.min_intensity:g}")
        if self.min_shindo is not None:
            lines.append(f"最小震度 (日本源): {self.min_shindo}")
        lines.append(f"预警更新: {UPDATE_LABELS[self.updates]}")
        return "\n".join(lines)


class SubscriptionStore(BaseSettings):
    """持久化在 configs/emergency_alerts/subscriptions.json"""

    subscriptions: list[Subscription] = Field(default_factory=list)

    def get(self, target: TargetKey) -> Subscription | None:
        return next((s for s in self.subscriptions if s.target == target), None)

    def upsert(self, sub: Subscription) -> None:
        self.subscriptions = [
            s for s in self.subscriptions if s.target != sub.target
        ] + [sub]

    def remove(self, target: TargetKey) -> bool:
        before = len(self.subscriptions)
        self.subscriptions = [s for s in self.subscriptions if s.target != target]
        return len(self.subscriptions) != before
