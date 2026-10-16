"""Wolfx 报文解析."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from mbplugin_emergency_alerts.quake import CST, JST, shindo_rank
from mbplugin_emergency_alerts.sources.wolfx import WolfxParseError, parse_message
from wolfx_samples import cenc_eew, cenc_eqlist, jma_eew, jma_eqlist, sc_eew


def test_control_messages_are_ignored():
    assert parse_message('{"type":"heartbeat","ver":24,"id":"1","timestamp":1}') is None
    assert parse_message({"type": "pong", "timestamp": 1}) is None
    assert parse_message({"type": "weather_rank"}) is None


def test_cenc_eew():
    q = parse_message(json.dumps(cenc_eew()))
    assert q is not None
    assert q.kind == "eew"
    assert q.event_key == ("cenc_eew", "202610161200.0001")
    assert q.seq == 1
    assert q.origin_time == datetime(2026, 10, 16, 12, 0, 2, tzinfo=CST)
    assert (q.magnitude, q.depth, q.intensity) == (5.2, None, 6.4)


def test_magnitude_falls_back_to_deprecated_spelling():
    raw = sc_eew()
    del raw["Magnitude"]
    q = parse_message(raw)
    assert q is not None and q.magnitude == 4.0


def test_jma_eew_uses_jst_and_keeps_shindo_text():
    q = parse_message(jma_eew(isWarn=True))
    assert q is not None
    assert q.origin_time.tzinfo is JST
    assert (q.seq, q.shindo, q.is_warn) == (3, "5-", True)
    assert "日本" in q.region_text


def test_jma_training_is_tagged():
    q = parse_message(jma_eew(isTraining=True))
    assert q is not None and "训练" in q.extra_tags


def test_cenc_eqlist_takes_the_latest_entry():
    q = parse_message(cenc_eqlist())
    assert q is not None
    assert q.kind == "report"
    assert (q.hypocenter, q.magnitude, q.depth, q.intensity) == (
        "四川雅安市宝兴县",
        5.1,
        10.0,
        6.0,
    )
    assert q.is_final and not q.automatic


def test_cenc_automatic_and_reviewed_are_different_reports_of_one_event():
    auto = parse_message(cenc_eqlist(type="automatic"))
    reviewed = parse_message(cenc_eqlist())
    assert auto is not None and reviewed is not None
    assert auto.event_key == reviewed.event_key
    assert auto.report_key != reviewed.report_key


def test_jma_eqlist_parses_depth_with_unit_and_note():
    q = parse_message(jma_eqlist())
    assert q is not None
    assert (q.depth, q.shindo) == (40.0, "4")
    assert "津波" in q.note


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2]",
        json.dumps(cenc_eew(HypoCenter="")),
        json.dumps(cenc_eew(OriginTime="yesterday")),
        json.dumps({"type": "cenc_eqlist", "md5": "x"}),
    ],
)
def test_malformed_messages_raise(raw):
    with pytest.raises(WolfxParseError):
        parse_message(raw)


def test_shindo_rank_orders_both_spellings():
    assert shindo_rank("5-") == shindo_rank("5弱") == 5
    assert shindo_rank("5+") == shindo_rank("5強") == 6
    assert shindo_rank("7") == 9
    assert shindo_rank("?") is None
