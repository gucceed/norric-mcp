from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _row(**kw):
    base = dict(orgnr="5567037485", orgnr_display="556703-7485", name="Spotify AB",
                orgform="AB-ORGFO", is_active=True,
                snapshot_date="2026-09-19", last_seen_at="2026-09-19T10:00:00+00:00")
    base.update(kw)
    return SimpleNamespace(**base)


def _db(rows, freshness=True):
    db = MagicMock()
    def execute(query, params=None):
        result = MagicMock()
        if "norric_field_changes" in str(query):
            result.__iter__ = lambda self: iter(rows)
        else:
            result.fetchone.return_value = SimpleNamespace(
                last_success=datetime.now(timezone.utc) if freshness else None,
                last_attempt=datetime.now(timezone.utc),
            )
        return result
    db.execute.side_effect = execute
    return db


def test_normalizes_and_groups_address_changes():
    from changes.company import company_changes
    rows = [
        _row(field_name="street", old_value="Old 1", new_value="New 2"),
        _row(field_name="postcode", old_value="11111", new_value="22222"),
    ]
    out = company_changes(_db(rows), event_types=["address_change"])
    assert out["data"]["count"] == 1
    event = out["data"]["events"][0]
    assert event["event_type"] == "address_change"
    assert event["orgnr"] == "556703-7485"
    assert len(event["changes"]) == 2
    assert event["evidence"]["reference_links"]["allabolag"].endswith("5567037485")


def test_classifies_rename_and_closure_without_guessing_merger():
    from changes.company import company_changes
    rows = [
        _row(field_name="name", old_value="Old AB", new_value="New AB"),
        _row(field_name="deregistered_at", old_value=None, new_value="2026-09-18"),
        _row(field_name="name", old_value="Target AB", new_value="Buyer AB"),
    ]
    out = company_changes(_db(rows), event_types=["rename", "closure", "merger"])
    assert {e["event_type"] for e in out["data"]["events"]} == {"rename", "closure"}
    assert any("merger" in w for w in out["warnings"])


def test_source_backed_registration_and_merger_when_fields_exist():
    from changes.company import company_changes
    rows = [
        _row(field_name="registreringsdatum", old_value=None, new_value="2026-09-18"),
        _row(field_name="avregistreringsorsak", old_value=None, new_value="fusion"),
    ]
    out = company_changes(_db(rows), event_types=["new_registration", "merger"])
    assert {e["event_type"] for e in out["data"]["events"]} == {"new_registration", "merger"}


def test_validates_input_bounds_and_event_types():
    from changes.company import company_changes
    with pytest.raises(ValueError):
        company_changes(_db([]), days=31)
    with pytest.raises(ValueError):
        company_changes(_db([]), limit=0)
    with pytest.raises(ValueError):
        company_changes(_db([]), event_types=["vibes"])


def test_empty_feed_is_honest():
    from changes.company import company_changes
    out = company_changes(_db([], freshness=False), event_types=["new_registration"])
    assert out["data"]["events"] == []
    assert out["confidence"] == 0.7
    assert len(out["warnings"]) == 2
