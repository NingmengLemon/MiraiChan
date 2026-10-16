"""Wolfx Open API 报文解析.

字段名以 https://wolfx.jp/zh/docs/open-api 为准, 并按实测报文修正:
时间格式国内源是 ``2026-10-09 12:22:08``, JMA 源是 ``2026/10/16 12:48:10``;
``Magunitude`` 是已弃用的拼写错误, 优先读 ``Magnitude``.

解析失败一律抛 ``WolfxParseError``, 由调用方记日志后丢弃这一条, 不影响连接.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ..quake import CST, JST, Quake, SourceInfo

__all__ = [
    "EEW_SOURCES",
    "REPORT_SOURCES",
    "SOURCES",
    "WolfxParseError",
    "parse_message",
]

EEW_SOURCES: dict[str, SourceInfo] = {
    "cenc_eew": SourceInfo("中国地震台网 地震预警", "eew", CST),
    "sc_eew": SourceInfo("四川省地震局 地震预警", "eew", CST),
    "fj_eew": SourceInfo("福建省地震局 地震预警", "eew", CST),
    "cq_eew": SourceInfo("重庆市地震局 地震预警", "eew", CST),
    "jma_eew": SourceInfo("日本气象厅 紧急地震速报", "eew", JST, frozenset({"日本"})),
}
REPORT_SOURCES: dict[str, SourceInfo] = {
    "cenc_eqlist": SourceInfo("中国地震台网 地震速报", "report", CST),
    "jma_eqlist": SourceInfo("日本气象厅 地震情报", "report", JST, frozenset({"日本"})),
}
SOURCES: dict[str, SourceInfo] = {**EEW_SOURCES, **REPORT_SOURCES}

#: 连接层面的报文, 不是地震信息
CONTROL_TYPES = frozenset({"heartbeat", "pong"})


class WolfxParseError(ValueError):
    pass


def _time(raw: Any, tz: timezone) -> datetime:
    if not isinstance(raw, str):
        raise WolfxParseError(f"时间字段不是字符串: {raw!r}")
    text = raw.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    raise WolfxParseError(f"无法解析时间: {raw!r}")


def _float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip().removesuffix("km").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _magnitude(d: Mapping[str, Any]) -> float | None:
    mag = _float(d.get("Magnitude"))
    return mag if mag is not None else _float(d.get("Magunitude"))


def _str(d: Mapping[str, Any], key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise WolfxParseError(f"缺少字段 {key!r}")
    return v.strip()


def _int(d: Mapping[str, Any], key: str, default: int = 1) -> int:
    v = d.get(key)
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v)
    return default


def _parse_cn_eew(source: str, d: Mapping[str, Any]) -> Quake:
    info = SOURCES[source]
    return Quake(
        source=source,
        info=info,
        event_id=_str(d, "EventID"),
        seq=_int(d, "ReportNum"),
        report_time=_time(d.get("ReportTime"), info.tz),
        origin_time=_time(d.get("OriginTime"), info.tz),
        hypocenter=_str(d, "HypoCenter"),
        latitude=_float(d.get("Latitude")),
        longitude=_float(d.get("Longitude")),
        magnitude=_magnitude(d),
        depth=_float(d.get("Depth")),
        intensity=_float(d.get("MaxIntensity")),
        is_final=bool(d.get("isFinal", False)),
        is_cancel=bool(d.get("isCancel", False)),
    )


def _parse_jma_eew(source: str, d: Mapping[str, Any]) -> Quake:
    info = SOURCES[source]
    shindo = d.get("MaxIntensity")
    return Quake(
        source=source,
        info=info,
        event_id=_str(d, "EventID"),
        seq=_int(d, "Serial"),
        report_time=_time(d.get("AnnouncedTime"), info.tz),
        origin_time=_time(d.get("OriginTime"), info.tz),
        hypocenter=_str(d, "Hypocenter"),
        latitude=_float(d.get("Latitude")),
        longitude=_float(d.get("Longitude")),
        magnitude=_magnitude(d),
        depth=_float(d.get("Depth")),
        shindo=str(shindo) if shindo is not None else None,
        is_final=bool(d.get("isFinal", False)),
        is_cancel=bool(d.get("isCancel", False)),
        is_warn=bool(d.get("isWarn", False)),
        # 训练报不应该推送, 解析时就标出来交给上层过滤
        extra_tags=frozenset({"训练"}) if d.get("isTraining") else frozenset(),
    )


def _latest_entry(d: Mapping[str, Any]) -> Mapping[str, Any]:
    entry = d.get("No1")
    if not isinstance(entry, Mapping):
        raise WolfxParseError("地震列表缺少 No1")
    return entry


def _parse_cenc_eqlist(source: str, d: Mapping[str, Any]) -> Quake:
    info = SOURCES[source]
    e = _latest_entry(d)
    automatic = e.get("type") == "automatic"
    time_raw = e.get("time")
    return Quake(
        source=source,
        info=info,
        # 同一次地震的自动测定与正式测定共用 EventID; 旧报文没有 EventID 时用发震时间兜底
        event_id=str(e.get("EventID") or time_raw),
        seq=1 if automatic else 2,
        report_time=_time(e.get("ReportTime") or time_raw, info.tz),
        origin_time=_time(time_raw, info.tz),
        hypocenter=_str(e, "location"),
        latitude=_float(e.get("latitude")),
        longitude=_float(e.get("longitude")),
        magnitude=_float(e.get("magnitude")),
        depth=_float(e.get("depth")),
        intensity=_float(e.get("intensity")),
        automatic=automatic,
        is_final=not automatic,
    )


def _parse_jma_eqlist(source: str, d: Mapping[str, Any]) -> Quake:
    info = SOURCES[source]
    e = _latest_entry(d)
    time_raw = e.get("time_full") or e.get("time")
    shindo = e.get("shindo")
    note = e.get("info")
    return Quake(
        source=source,
        info=info,
        event_id=str(e.get("EventID") or time_raw),
        seq=1,
        report_time=_time(time_raw, info.tz),
        origin_time=_time(time_raw, info.tz),
        hypocenter=_str(e, "location"),
        latitude=_float(e.get("latitude")),
        longitude=_float(e.get("longitude")),
        magnitude=_float(e.get("magnitude")),
        depth=_float(e.get("depth")),
        shindo=str(shindo) if shindo else None,
        is_final=True,
        note=note.strip() if isinstance(note, str) else "",
    )


_PARSERS = {
    "cenc_eew": _parse_cn_eew,
    "sc_eew": _parse_cn_eew,
    "fj_eew": _parse_cn_eew,
    "cq_eew": _parse_cn_eew,
    "jma_eew": _parse_jma_eew,
    "cenc_eqlist": _parse_cenc_eqlist,
    "jma_eqlist": _parse_jma_eqlist,
}


def parse_message(raw: str | Mapping[str, Any]) -> Quake | None:
    """解析一条 ws 报文.

    Returns:
        地震信息; 心跳 / pong / 不关心的类型返回 None

    Raises:
        WolfxParseError: 是已知的地震类型, 但内容不合法
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise WolfxParseError(f"不是 JSON: {e}") from None
    else:
        data = raw
    if not isinstance(data, Mapping):
        raise WolfxParseError("报文不是 JSON 对象")
    msg_type = data.get("type")
    if not isinstance(msg_type, str) or msg_type in CONTROL_TYPES:
        return None
    parser = _PARSERS.get(msg_type)
    if parser is None:
        return None
    return parser(msg_type, data)
