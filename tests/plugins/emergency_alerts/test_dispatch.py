"""订阅匹配与推送决策."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from mbplugin_emergency_alerts.dispatch import Dispatcher
from mbplugin_emergency_alerts.quake import CST, Quake
from mbplugin_emergency_alerts.sources.wolfx import parse_message
from mbplugin_emergency_alerts.subscription import Subscription, SubscriptionStore
from pydantic import ValidationError
from wolfx_samples import cenc_eew, cenc_eqlist, jma_eew

NOW = datetime(2026, 10, 16, 12, 0, 30, tzinfo=CST)


def q(raw) -> Quake:
    got = parse_message(raw)
    assert got is not None
    return got


def sub(**kw) -> Subscription:
    return Subscription(
        target_type=kw.pop("target_type", "group"),
        target_id=kw.pop("target_id", 1),
        **kw,
    )


def dispatcher(now: datetime = NOW) -> Dispatcher:
    return Dispatcher(now=lambda: now)


class TestMatching:
    def test_default_subscription_matches_a_moderate_quake(self):
        assert sub().matches(q(cenc_eew()))

    def test_kind_filter(self):
        assert not sub(kinds=["report"]).matches(q(cenc_eew()))

    def test_source_filter(self):
        assert not sub(sources=["sc_eew"]).matches(q(cenc_eew()))
        assert sub(sources=["cenc_eew"]).matches(q(cenc_eew()))

    def test_region_keywords_are_substrings_of_the_hypocenter(self):
        assert sub(regions=["雅安"]).matches(q(cenc_eew()))
        assert not sub(regions=["云南", "西藏"]).matches(q(cenc_eew()))

    def test_japan_keyword_matches_japanese_place_names(self):
        assert sub(regions=["日本"]).matches(q(jma_eew()))

    def test_magnitude_threshold(self):
        assert not sub(min_magnitude=5.5).matches(q(cenc_eew()))

    def test_intensity_threshold_ignores_sources_without_intensity(self):
        s = sub(min_intensity=7)
        assert not s.matches(q(cenc_eew()))
        assert s.matches(q(jma_eew()))

    def test_shindo_threshold_ignores_chinese_sources(self):
        s = sub(min_shindo="5+")
        assert not s.matches(q(jma_eew()))
        assert s.matches(q(cenc_eew()))

    def test_disabled_subscription_matches_nothing(self):
        assert not sub(enabled=False).matches(q(cenc_eew()))

    @pytest.mark.parametrize(
        "bad",
        [
            {"sources": ["nope"]},
            {"kinds": []},
            {"min_shindo": "8"},
            {"min_magnitude": -1},
        ],
    )
    def test_invalid_settings_are_rejected(self, bad):
        with pytest.raises(ValidationError):
            sub(**bad)


class TestStore:
    def test_one_subscription_per_target(self):
        store = SubscriptionStore()
        store.upsert(sub(min_magnitude=3))
        store.upsert(sub(min_magnitude=5))
        store.upsert(sub(target_type="private"))
        assert len(store.subscriptions) == 2
        got = store.get(("group", 1))
        assert got is not None and got.min_magnitude == 5

    def test_group_and_private_with_same_id_are_different_targets(self):
        store = SubscriptionStore()
        store.upsert(sub(target_type="private", target_id=1))
        assert store.get(("group", 1)) is None

    def test_round_trips_through_json(self):
        store = SubscriptionStore(
            subscriptions=[sub(regions=["四川"], min_shindo="5-")]
        )
        assert SubscriptionStore.model_validate_json(store.model_dump_json()) == store


class TestDispatcher:
    def test_pushes_a_fresh_report_to_matching_subscriptions(self):
        a, b = sub(target_id=1), sub(target_id=2, regions=["云南"])
        assert dispatcher().select(q(cenc_eew()), [a, b]) == [a]

    def test_same_report_is_handled_once(self):
        d, s = dispatcher(), sub(updates="all")
        assert d.select(q(cenc_eew()), [s]) == [s]
        assert d.select(q(cenc_eew()), [s]) == []

    def test_stale_reports_are_dropped(self):
        late = NOW + timedelta(hours=1)
        assert dispatcher(late).select(q(cenc_eew()), [sub()]) == []

    def test_reports_have_a_longer_max_age_than_eew(self):
        later = datetime(2026, 10, 16, 12, 40, tzinfo=CST)
        assert dispatcher(later).select(q(cenc_eqlist()), [sub()])

    def test_training_messages_are_never_pushed(self):
        jst_now = datetime(2026, 10, 16, 12, 0, 40, tzinfo=CST)
        assert dispatcher(jst_now).select(q(jma_eew(isTraining=True)), [sub()]) == []

    def test_update_policy_first(self):
        d, s = dispatcher(), sub(updates="first")
        assert d.select(q(cenc_eew()), [s]) == [s]
        assert d.select(q(cenc_eew(ReportNum=2, isFinal=True)), [s]) == []

    def test_update_policy_final(self):
        d, s = dispatcher(), sub(updates="final")
        assert d.select(q(cenc_eew()), [s]) == [s]
        assert d.select(q(cenc_eew(ReportNum=2)), [s]) == []
        assert d.select(q(cenc_eew(ReportNum=3, isFinal=True)), [s]) == [s]
        assert d.select(q(cenc_eew(ReportNum=4, isFinal=True)), [s]) == []

    def test_update_policy_all(self):
        d, s = dispatcher(), sub(updates="all")
        for n in (1, 2, 3):
            assert d.select(q(cenc_eew(ReportNum=n)), [s]) == [s]

    def test_first_push_happens_when_a_later_report_crosses_the_threshold(self):
        d, s = dispatcher(), sub(min_magnitude=5.5, updates="first")
        assert d.select(q(cenc_eew(Magnitude=5.0)), [s]) == []
        assert d.select(q(cenc_eew(ReportNum=2, Magnitude=5.8)), [s]) == [s]

    def test_cancel_goes_only_to_subscriptions_that_got_the_event(self):
        d = dispatcher()
        got, missed = sub(target_id=1), sub(target_id=2, min_magnitude=6)
        d.select(q(cenc_eew()), [got, missed])
        cancel = q(cenc_eew(ReportNum=2, isCancel=True, Magnitude=1.0))
        assert d.select(cancel, [got, missed]) == [got]

    def test_different_events_are_independent(self):
        d, s = dispatcher(), sub(updates="first")
        assert d.select(q(cenc_eew()), [s]) == [s]
        assert d.select(q(cenc_eew(EventID="other")), [s]) == [s]
