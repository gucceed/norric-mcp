"""
Tests for changes/dk_company.py - danish_company_changes_v1 CVR change feed.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from datetime import date, datetime, timezone


def _ns(**kw):
    return SimpleNamespace(**kw)


def _mock_db(change_rows=None, pipeline_rows=None):
    db = MagicMock()

    def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "norric_dk_field_changes" in sql:
            result.__iter__ = lambda self: iter(change_rows or [])
            result.fetchall.return_value = change_rows or []
            result.fetchone.return_value = None
        elif "norric_pipeline_runs" in sql:
            result.fetchall.return_value = pipeline_rows or []
            result.fetchone.return_value = None
        else:
            result.fetchone.return_value = None
        return result

    db.execute.side_effect = execute_side_effect
    return db


TODAY = date.today().isoformat()


class TestEventTypeMapping:
    def test_rename(self):
        from changes.dk_company import _event_type
        assert _event_type("name", "Old ApS", "New ApS") == "rename"

    def test_address(self):
        from changes.dk_company import _event_type
        assert _event_type("street", "A", "B") == "address_change"
        assert _event_type("municipality_code", "0101", "0530") == "address_change"

    def test_closure_by_flag(self):
        from changes.dk_company import _event_type
        assert _event_type("is_active", "True", "False") == "closure"

    def test_closure_by_ceased_date(self):
        from changes.dk_company import _event_type
        assert _event_type("ceased_at", None, "2026-09-01") == "closure"

    def test_closure_by_danish_status(self):
        from changes.dk_company import _event_type
        assert _event_type("status_code", "NORMAL", "OPHØRT") == "closure"

    def test_merger_needs_fusion_evidence(self):
        from changes.dk_company import _event_type
        assert _event_type("status_code", "NORMAL", "OPLØST EFTER FUSION") == "merger"
        # a plain rename or status change never becomes a merger
        assert _event_type("name", "A ApS", "B ApS") != "merger"

    def test_new_registration_needs_empty_old(self):
        from changes.dk_company import _event_type
        assert _event_type("started_at", None, "2026-09-01") == "new_registration"
        assert _event_type("started_at", "2020-01-01", "2026-09-01") is None


class TestCompanyChanges:
    def test_happy_path_groups_fields(self):
        from changes.dk_company import company_changes
        rows = [
            _ns(cvr_number="54562519", snapshot_date=TODAY, field_name="street",
                old_value="A", new_value="B", change_source="cvr_events",
                name="LEGO A/S", legal_form_code="80", is_active=True,
                last_seen_at=datetime.now(timezone.utc)),
            _ns(cvr_number="54562519", snapshot_date=TODAY, field_name="city",
                old_value="X", new_value="Billund", change_source="cvr_events",
                name="LEGO A/S", legal_form_code="80", is_active=True,
                last_seen_at=datetime.now(timezone.utc)),
        ]
        db = _mock_db(change_rows=rows, pipeline_rows=[
            _ns(pipeline="cvr_events", last_success=datetime.now(timezone.utc),
                last_attempt=None)])
        out = company_changes(db, days=7)
        d = out["data"]
        assert d["country"] == "DK"
        assert d["count"] == 1
        ev = d["events"][0]
        assert ev["event_type"] == "address_change"
        assert ev["cvr_number"] == "54562519"
        assert len(ev["changes"]) == 2
        assert ev["evidence"]["license"].startswith("CC BY 4.0")
        assert d["source_freshness"]["cvr_events"]["last_success"]

    def test_validation(self):
        from changes.dk_company import company_changes
        db = _mock_db()
        with pytest.raises(ValueError):
            company_changes(db, days=0)
        with pytest.raises(ValueError):
            company_changes(db, limit=0)
        with pytest.raises(ValueError):
            company_changes(db, event_types=["fabricated_event"])
        with pytest.raises(ValueError):
            company_changes(db, cvr_number="123")

    def test_empty_window_warns_honestly(self):
        from changes.dk_company import company_changes
        db = _mock_db(change_rows=[])
        out = company_changes(db, days=7)
        assert out["data"]["count"] == 0
        assert any("No matching" in w for w in out["warnings"])
        # the no-inference disclaimer fires for new_registration/merger
        assert any("first-seen" in w for w in out["warnings"])
