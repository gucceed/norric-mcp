"""
Tests for verify/dk_company.py - danish_company_verify_v1 CVR verification.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from datetime import datetime, timezone


def _ns(**kw):
    return SimpleNamespace(**kw)


def _mock_db(entity=None, name_rows=None, changes=None, pipelines=None):
    db = MagicMock()

    def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "norric_dk_field_changes" in sql:
            result.__iter__ = lambda self: iter(changes or [])
            result.fetchone.return_value = None
        elif "norric_pipeline_runs" in sql:
            result.__iter__ = lambda self: iter(pipelines or [])
            result.fetchone.return_value = None
        elif "ILIKE" in sql:
            result.__iter__ = lambda self: iter(name_rows or [])
            result.fetchone.return_value = None
        elif "norric_dk_entities" in sql:
            result.fetchone.return_value = entity
        else:
            result.fetchone.return_value = None
        return result

    db.execute.side_effect = execute_side_effect
    db.rollback = MagicMock()
    return db


ENTITY = _ns(
    cvr_number="54562519", name="LEGO A/S",
    legal_form_code="80", legal_form_label="Aktieselskab",
    status_code="NORMAL", status_label="Normal",
    is_active=True, started_at="1932-08-10", ceased_at=None,
    industry_code="32.40.00", industry_label="Fremstilling af spil og legetøj",
    street="Aastvej 1", city="Billund", postcode="7190",
    municipality_code="530", country_code="DK",
    phone=None, email=None, website=None,
    source="cvr_fildownload",
    registrering_fra="2000-01-01T00:00:00+01:00",
    virkning_fra="1932-08-10",
    first_seen_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    last_seen_at=datetime.now(timezone.utc),
    last_updated_at=datetime.now(timezone.utc),
)


class TestNormalizeCvr:
    def test_plain(self):
        from ingestion.cvr.normalize import normalize_cvr_number
        assert normalize_cvr_number("54562519") == "54562519"

    def test_seven_digits_zero_padded(self):
        from ingestion.cvr.normalize import normalize_cvr_number
        assert normalize_cvr_number("1234567") == "01234567"

    def test_spaces_and_dash(self):
        from ingestion.cvr.normalize import normalize_cvr_number
        assert normalize_cvr_number("54 56 25 19") == "54562519"
        assert normalize_cvr_number("54-56-25-19") == "54562519"

    def test_invalid(self):
        from ingestion.cvr.normalize import normalize_cvr_number
        for bad in ("123", "abcdefghi", "123456789"):
            with pytest.raises(ValueError):
                normalize_cvr_number(bad)


class TestVerifyCompany:
    def test_not_found(self):
        from verify.dk_company import verify_company
        db = _mock_db(entity=None)
        out = verify_company(db, "54562519")
        assert out["data"]["found"] is False
        assert out["data"]["verified"] is False
        assert out["data"]["match"] == "none"

    def test_ambiguous_name_returns_candidates(self):
        from verify.dk_company import verify_company
        rows = [
            _ns(cvr_number="54562519", name="LEGO A/S", is_active=True),
            _ns(cvr_number="12345678", name="LEGO Holding A/S", is_active=True),
        ]
        db = _mock_db(name_rows=rows)
        out = verify_company(db, "LEGO")
        assert out["data"]["match"] == "ambiguous"
        assert len(out["data"]["candidates"]) == 2
        assert out["data"]["verified"] is None

    def test_active_company_happy_path(self):
        from verify.dk_company import verify_company
        db = _mock_db(
            entity=ENTITY,
            changes=[_ns(snapshot_date="2026-09-01", field_name="street",
                         old_value="A", new_value="B", source="cvr_events")],
            pipelines=[_ns(pipeline="cvr_bulk",
                           last_success=datetime.now(timezone.utc),
                           last_attempt=datetime.now(timezone.utc))],
        )
        out = verify_company(db, "54562519")
        d = out["data"]
        assert d["found"] is True and d["verified"] is True
        assert d["country"] == "DK"
        assert d["identity"]["cvr_number"] == "54562519"
        assert d["identity"]["name"] == "LEGO A/S"
        assert d["identity"]["legal_form"]["label"] == "Aktieselskab"
        assert d["legal_status"]["is_active"] is True
        assert d["registrations"]["vat"]["status"] == "not_tracked"
        assert d["risk"] is None
        assert d["latest_changes"][0]["field"] == "street"
        assert "cvr_bulk" in d["sources"]
        assert d["evidence"]["license"].startswith("CC BY 4.0")
        assert out["confidence"] >= 0.8

    def test_ceased_company_flags_signal(self):
        from verify.dk_company import verify_company
        ceased = _ns(**{**ENTITY.__dict__, "is_active": False,
                        "ceased_at": "2026-01-15",
                        "last_seen_at": datetime.now(timezone.utc)})
        db = _mock_db(entity=ceased)
        out = verify_company(db, "54562519")
        assert out["data"]["verified"] is False
        assert out["data"]["legal_status"]["ceased_at"] == "2026-01-15"
        assert any(s["key"] == "ceased" for s in out["signals"])

    def test_never_fabricates_untracked_fields(self):
        from verify.dk_company import verify_company
        db = _mock_db(entity=ENTITY)
        out = verify_company(db, "54562519")
        assert out["data"]["registrations"]["employer"]["status"] == "not_tracked"
        assert out["data"]["identity"]["contact"]["phone"] is None
