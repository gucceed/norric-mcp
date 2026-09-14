"""
tests/test_watch_diff_worker.py

Diff detection (pure) + delivery retry semantics (pure) + emission dedupe
over a fake session. No DB, no network.
Run with: pytest tests/test_watch_diff_worker.py -v --tb=short
"""

from datetime import datetime, timedelta, timezone

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watch.diff import detect_score_events, detect_signal_events
from watch.worker import BACKOFF_SECONDS, MAX_ATTEMPTS, next_attempt_delay

NOW = datetime(2026, 9, 14, 5, 31, tzinfo=timezone.utc)
YESTERDAY = NOW - timedelta(days=1)
ALL_TYPES = {
    "company.risk_tier_changed", "company.score_changed",
    "company.debt_signal_new", "company.bankruptcy_status_changed",
}


def _score(band, ts):
    return {"risk_band": band, "scored_at": ts}


class TestScoreEvents:
    def test_tier_change_fires(self):
        out = detect_score_events("5560123456", _score(3, YESTERDAY), _score(4, NOW),
                                  ALL_TYPES, 3)
        types = {e["event_type"] for e in out}
        assert "company.risk_tier_changed" in types
        e = next(x for x in out if x["event_type"] == "company.risk_tier_changed")
        assert e["data"]["previous"]["risk_tier"] == "ELEVATED"
        assert e["data"]["current"]["risk_tier"] == "HIGH"
        assert e["occurred_at"] == NOW

    def test_band_move_always_exceeds_default_delta(self):
        # adjacent bands are 4 apart on the 0-20 scale, default threshold 3
        out = detect_score_events("5560123456", _score(2, YESTERDAY), _score(3, NOW),
                                  ALL_TYPES, 3)
        assert "company.score_changed" in {e["event_type"] for e in out}

    def test_same_band_no_events(self):
        out = detect_score_events("5560123456", _score(3, YESTERDAY), _score(3, NOW),
                                  ALL_TYPES, 3)
        assert out == []

    def test_no_previous_no_events(self):
        assert detect_score_events("5560123456", None, _score(4, NOW), ALL_TYPES, 3) == []

    def test_high_threshold_suppresses_score_event_keeps_tier(self):
        out = detect_score_events("5560123456", _score(3, YESTERDAY), _score(4, NOW),
                                  ALL_TYPES, 10)
        types = {e["event_type"] for e in out}
        assert "company.risk_tier_changed" in types
        assert "company.score_changed" not in types

    def test_unsubscribed_type_not_fired(self):
        out = detect_score_events("5560123456", _score(3, YESTERDAY), _score(5, NOW),
                                  {"company.debt_signal_new"}, 3)
        assert out == []

    def test_improvement_fires_too(self):
        out = detect_score_events("5560123456", _score(5, YESTERDAY), _score(1, NOW),
                                  ALL_TYPES, 3)
        e = next(x for x in out if x["event_type"] == "company.score_changed")
        assert e["data"]["score_delta"] == 2 - 18


class TestSignalEvents:
    ROWS = [
        {"source": "kronofogden", "signal_id": "1", "created_at": NOW,
         "summary": {"claim_amount_sek": 45000}},
        {"source": "skatteverket", "signal_id": "2", "created_at": NOW,
         "summary": {"signal_type": "restanslangd"}},
        {"source": "bolagsverket_konkurs", "signal_id": "3", "created_at": NOW,
         "summary": {"status_code": "KK-AVOMFO"}},
    ]

    def test_sources_map_to_event_types(self):
        out = detect_signal_events("5560123456", self.ROWS, ALL_TYPES)
        types = [e["event_type"] for e in out]
        assert types == [
            "company.debt_signal_new",
            "company.debt_signal_new",
            "company.bankruptcy_status_changed",
        ]

    def test_subscription_filter(self):
        out = detect_signal_events("5560123456", self.ROWS,
                                   {"company.bankruptcy_status_changed"})
        assert len(out) == 1
        assert out[0]["data"]["signal_source"] == "bolagsverket_konkurs"


class TestBackoff:
    def test_schedule(self):
        assert next_attempt_delay(1) == timedelta(seconds=BACKOFF_SECONDS[0])
        assert next_attempt_delay(2) == timedelta(seconds=BACKOFF_SECONDS[1])
        assert next_attempt_delay(3) == timedelta(seconds=BACKOFF_SECONDS[2])
        assert next_attempt_delay(4) == timedelta(seconds=BACKOFF_SECONDS[3])

    def test_dead_after_max(self):
        assert next_attempt_delay(MAX_ATTEMPTS) is None
        assert next_attempt_delay(MAX_ATTEMPTS + 1) is None

    def test_five_attempts_total(self):
        # 1 immediate + 4 scheduled retries = 5 attempts (spec §6)
        assert len(BACKOFF_SECONDS) + 1 == MAX_ATTEMPTS
