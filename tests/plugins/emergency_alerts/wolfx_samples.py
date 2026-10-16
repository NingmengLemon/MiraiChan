"""构造的 Wolfx 报文. 字段形状照抄 2026-10 实测的真实报文, 数值是编的."""

from __future__ import annotations

from typing import Any


def cenc_eew(**over: Any) -> dict[str, Any]:
    return {
        "type": "cenc_eew",
        "ID": "abc123",
        "EventID": "202610161200.0001",
        "ReportTime": "2026-10-16 12:00:10",
        "ReportNum": 1,
        "OriginTime": "2026-10-16 12:00:02",
        "HypoCenter": "四川雅安市宝兴县",
        "Latitude": 30.27,
        "Longitude": 102.85,
        "Magnitude": 5.2,
        "Depth": None,
        "MaxIntensity": 6.4,
        **over,
    }


def sc_eew(**over: Any) -> dict[str, Any]:
    # 地方局报文同时带弃用的 Magunitude 与新的 Magnitude
    return {
        "type": "sc_eew",
        "ID": 8201,
        "EventID": "202610161200.0001_2",
        "ReportTime": "2026-10-16 12:00:12",
        "ReportNum": 2,
        "OriginTime": "2026-10-16 12:00:02",
        "HypoCenter": "四川雅安市宝兴县",
        "Latitude": 30.27,
        "Longitude": 102.855,
        "Magunitude": 4.0,
        "Magnitude": 4.0,
        "Depth": 0.0,
        "MaxIntensity": 5.6,
        **over,
    }


def jma_eew(**over: Any) -> dict[str, Any]:
    return {
        "type": "jma_eew",
        "Title": "緊急地震速報（予報）",
        "EventID": "20261016130010",
        "Serial": 3,
        "AnnouncedTime": "2026/10/16 13:00:30",
        "OriginTime": "2026/10/16 13:00:05",
        "Hypocenter": "千葉県東方沖",
        "Latitude": 35.5,
        "Longitude": 140.8,
        "Magunitude": 5.6,
        "Magnitude": 5.6,
        "Depth": 40,
        "MaxIntensity": "5-",
        "isSea": True,
        "isTraining": False,
        "isAssumption": False,
        "isWarn": False,
        "isFinal": False,
        "isCancel": False,
        **over,
    }


def cenc_eqlist(**entry_over: Any) -> dict[str, Any]:
    entry = {
        "type": "reviewed",
        "EventID": "CC.20261016120002.1",
        "time": "2026-10-16 12:00:02",
        "ReportTime": "2026-10-16 12:10:00",
        "location": "四川雅安市宝兴县",
        "placeName": "四川雅安市宝兴县",
        "magnitude": "5.1",
        "depth": "10",
        "latitude": "30.27",
        "longitude": "102.85",
        "intensity": "6",
        **entry_over,
    }
    return {"type": "cenc_eqlist", "No1": entry, "No2": {}, "md5": "x"}


def jma_eqlist(**entry_over: Any) -> dict[str, Any]:
    entry = {
        "Title": "震源・震度情報",
        "EventID": "20261016130010",
        "time": "2026/10/16 13:00",
        "time_full": "2026/10/16 13:00:00",
        "location": "千葉県東方沖",
        "magnitude": "5.4",
        "shindo": "4",
        "depth": "40km",
        "latitude": "35.5",
        "longitude": "140.8",
        "info": "この地震による津波の心配はありません。",
        **entry_over,
    }
    return {"type": "jma_eqlist", "No1": entry, "md5": "x"}
