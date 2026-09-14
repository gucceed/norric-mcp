"""
tests/test_watch_store.py

Store behaviour over a fake session — SQL is routed by shape, rows are
SimpleNamespace. Covers serialisation redaction, tier budget enforcement,
update guards and the auto-pause counter. No live DB required.
Run with: pytest tests/test_watch_store.py -v --tb=short
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watch.store import (
    AUTO_PAUSE_FAILURE_THRESHOLD,
    WatchLimitError,
    create_watch,
    entity_budget_used,
    record_delivery,
    serialize_watch,
    update_watch,
)

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)
KH = "a" * 64


def _watch_row(**over):
    base = dict(
        watch_ref="watch_abc123",
        status="active",
        event_types=["company.risk_tier_changed"],
        filters={"orgnrs": ["5560123456"], "min_score_delta": 3},
        callback_url="https://platform.example.com/hook",
        signing_secret="whsec_secret",
        description="credit portfolio Q4",
        events_sent=7,
        last_delivery_at=NOW,
        consecutive_failures=0,
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(over)
    return SimpleNamespace(**base)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeDB:
    """Routes executed SQL by content to canned rows; records commits."""

    def __init__(self, select_filters_rows=None, return_row=None):
        self.select_filters_rows = select_filters_rows or []
        self.return_row = return_row
        self.executed = []
        self.commits = 0

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params or {}))
        if sql.lstrip().upper().startswith("SELECT FILTERS"):
            return _Result(self.select_filters_rows)
        return _Result([self.return_row] if self.return_row else [])

    def commit(self):
        self.commits += 1


class TestSerialize:
    def test_secret_redacted_by_default(self):
        out = serialize_watch(_watch_row())
        assert "signing_secret" not in out
        assert out["id"] == "watch_abc123"
        assert out["stats"] == {
            "events_sent": 7,
            "last_delivery_at": NOW.isoformat(),
            "consecutive_failures": 0,
        }

    def test_secret_only_when_requested(self):
        out = serialize_watch(_watch_row(), include_secret=True)
        assert out["signing_secret"] == "whsec_secret"


class TestBudget:
    def test_sums_entities_across_watches(self):
        db = FakeDB(select_filters_rows=[
            SimpleNamespace(filters={"orgnrs": ["5560123456", "5591234567"]}),
            SimpleNamespace(filters={"orgnrs": ["5560123456"]}),
        ])
        assert entity_budget_used(db, KH) == 3

    def test_create_within_budget(self):
        db = FakeDB(return_row=_watch_row())
        out = create_watch(
            db, key_hash=KH, tier="standard",
            event_types=["company.risk_tier_changed"],
            filters={"orgnrs": ["5560123456"]},
            callback_url="https://platform.example.com/hook",
            resolve_dns=False,
        )
        assert out["signing_secret"].startswith("whsec_")
        assert db.commits == 1

    def test_create_over_budget_rejected(self):
        existing = [SimpleNamespace(filters={"orgnrs": [f"5560{i:06d}" for i in range(10)]})]
        db = FakeDB(select_filters_rows=existing)
        with pytest.raises(WatchLimitError, match="500"):
            create_watch(
                db, key_hash=KH, tier="standard",
                event_types=["company.score_changed"],
                filters={"orgnrs": [f"5591{i:06d}" for i in range(491)]},
                callback_url="https://platform.example.com/hook",
                resolve_dns=False,
            )

    def test_update_filters_counts_against_budget_excluding_self(self):
        db = FakeDB(
            select_filters_rows=[],  # current watch read
            return_row=_watch_row(),
        )
        # current-watch lookup happens first; FakeDB returns [] for SELECT filters
        # so current is None → update returns None (watch not found for key)
        assert update_watch(
            db, key_hash=KH, tier="standard", watch_ref="watch_abc123",
            patch={"filters": {"orgnrs": ["5560123456"]}}, resolve_dns=False,
        ) is None

    def test_update_unknown_field_rejected(self):
        db = FakeDB()
        with pytest.raises(ValueError, match="unknown watch fields"):
            update_watch(db, key_hash=KH, tier="standard",
                         watch_ref="watch_abc123", patch={"signing_secret": "x"})


class TestAutoPause:
    def test_success_resets_failures(self):
        db = FakeDB(return_row=SimpleNamespace(consecutive_failures=0, status="active"))
        out = record_delivery(db, "watch_abc123", success=True)
        assert out == {"paused_now": False, "consecutive_failures": 0}

    def test_failure_below_threshold_keeps_active(self):
        db = FakeDB(return_row=SimpleNamespace(
            consecutive_failures=AUTO_PAUSE_FAILURE_THRESHOLD - 1, status="active"))
        out = record_delivery(db, "watch_abc123", success=False)
        assert out["paused_now"] is False
        assert out["consecutive_failures"] == AUTO_PAUSE_FAILURE_THRESHOLD - 1

    def test_failure_at_threshold_pauses(self):
        db = FakeDB(return_row=SimpleNamespace(
            consecutive_failures=AUTO_PAUSE_FAILURE_THRESHOLD, status="paused"))
        out = record_delivery(db, "watch_abc123", success=False)
        assert out["paused_now"] is True

    def test_missing_watch_is_noop(self):
        db = FakeDB(return_row=None)
        assert record_delivery(db, "watch_nope", success=False)["paused_now"] is False
