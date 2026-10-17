"""与数据源无关的地震报文模型.

各数据源的解析器都产出 ``Quake``; 订阅匹配、去重、推送格式化只认这个模型.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

__all__ = ["CST", "JST", "Quake", "QuakeKind", "SourceInfo", "shindo_rank"]

CST = timezone(timedelta(hours=8), name="CST")
JST = timezone(timedelta(hours=9), name="JST")

type QuakeKind = Literal["eew", "report"]
"""eew: 地震预警 (震后数秒, 多报更新); report: 地震速报/地震情报 (测定后发布)"""


@dataclass(frozen=True, slots=True)
class SourceInfo:
    name: str
    kind: QuakeKind
    tz: timezone
    #: 匹配地区关键词时额外附加的标签. 日本气象厅的震源地是日文地名, 加上 "日本" 才能被
    #: "日本" 这个关键词订阅到
    tags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Quake:
    source: str
    """数据源标识, 例如 ``cenc_eew``"""
    info: SourceInfo
    event_id: str
    seq: int
    """预警是第几报; 速报里 1 为自动测定, 2 为正式测定"""
    report_time: datetime
    origin_time: datetime
    hypocenter: str
    latitude: float | None = None
    longitude: float | None = None
    magnitude: float | None = None
    depth: float | None = None
    intensity: float | None = None
    """中国地震烈度 (预估最大烈度 / 最大烈度)"""
    shindo: str | None = None
    """日本震度, 原样保留 ("5-" / "5弱" / "7" 等)"""
    is_final: bool = False
    is_cancel: bool = False
    is_warn: bool = False
    """JMA 紧急地震速报是否为警报 (否则为预报)"""
    automatic: bool = False
    """速报是否为自动测定"""
    note: str = ""
    """附加信息, 例如 JMA 地震情报的津波信息"""
    extra_tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def kind(self) -> QuakeKind:
        return self.info.kind

    @property
    def event_key(self) -> tuple[str, str]:
        return (self.source, self.event_id)

    @property
    def report_key(self) -> tuple[str, str, int]:
        return (self.source, self.event_id, self.seq)

    @property
    def region_text(self) -> str:
        """地区关键词匹配的对象: 震源地加上数据源标签"""
        return " ".join([self.hypocenter, *sorted(self.info.tags | self.extra_tags)])


_SHINDO_RANKS = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5-": 5,
    "5弱": 5,
    "5+": 6,
    "5強": 6,
    "5强": 6,
    "6-": 7,
    "6弱": 7,
    "6+": 8,
    "6強": 8,
    "6强": 8,
    "7": 9,
}


def shindo_rank(shindo: str | None) -> int | None:
    """把日本震度转成可比较的序数 (1..9); 不认识的写法返回 None"""
    if shindo is None:
        return None
    return _SHINDO_RANKS.get(shindo.strip())
