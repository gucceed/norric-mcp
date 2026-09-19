"""
Tests for verify/company.py — swedish_company_verify_v1 registry verification.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from datetime import datetime, timezone


def _ns(**kw):
    return SimpleNamespace(**kw)


def _mock_db(entity=None, name_rows=None, profile=None, konkurs_rows=None,
             kron=None, tax=None, score=None, changes=None, pipelines=None):
    """Mock DB session dispatching on SQL content, mirroring test_kreditvakt_scorer."""
    db = MagicMock()

    def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "norric_field_changes" in sql:
            result.__iter__ = lambda self: iter(changes or [])
            result.fetchone.return_value = None
        elif "norric_pipeline_runs" in sql:
            result.__iter__ = lambda self: iter(pipelines or [])
            result.fetchone.return_value = None
        elif "company_profiles" in sql:
            result.fetchone.return_value = profile
        elif "company_scores" in sql:
            result.fetchone.return_value = score
        elif "norric_tax_signals" in sql:
            result.fetchone.return_value = tax
        elif "norric_payment_signals" in sql and "= 'konkurs'" in sql:
            result.__iter__ = lambda self: iter(konkurs_rows or [])
            result.fetchone.return_value = None
        elif "norric_payment_signals" in sql:
            result.fetchone.return_value = kron
        elif "ILIKE" in sql:
            result.__iter__ = lambda self: iter(name_rows or [])
            result.fetchone.return_value = None
        elif "norric_entities" in sql:
            result.fetchone.return_value = entity
        else:
            result.fetchone.return_value = None
        return result

    db.execute.side_effect = execute_side_effect
    db.rollback = MagicMock()
    return db


ENTITY = _ns(
    orgnr="556703-7485", orgnr_display="556703-7485", name="Spotify AB",
    orgform="AB", is_active=True, deregistered_at=None,
    street="Birger Jarlsgatan 61", city="Stockholm", postcode="113 56",
    kommunkod="0180", county="Stockholms län", source="bolagsverket_bulk",
    first_seen_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    last_seen_at=datetime.now(timezone.utc),
    last_updated_at=datetime.now(timezone.utc),
)


class TestNormalizeOrgnr:
    def test_plain_digits(self):
        from verify.company import normalize_orgnr
        assert normalize_orgnr("5567037485") == "556703-7485"

    def test_dashed(self):
        from verify.company import normalize_orgnr
        assert normalize_orgnr("556703-7485") == "556703-7485"

    def test_spaces(self):
        from verify.company import normalize_orgnr
        assert normalize_orgnr("556703 7485") == "556703-7485"

    def test_invalid(self):
        from verify.company import normalize_orgnr
        with pytest.raises(ValueError):
            normalize_orgnr("123")


class TestVerifyCompany:
    def test_not_found(self):
        from verify.company import verify_company
        db = _mock_db(entity=None)
        out = verify_company(db, "556703-7485")
        assert out["data"]["found"] is False
        assert out["data"]["verified"] is False
        assert out["data"]["match"] == "none"

    def test_ambiguous_name_returns_candidates(self):
        from verify.company import verify_company
        rows = [
            _ns(orgnr="556703-7485", name="Spotify AB", is_active=True),
            _ns(orgnr="559999-0000", name="Spotify Holding AB", is_active=True),
        ]
        db = _mock_db(name_rows=rows)
        out = verify_company(db, "Spotify")
        assert out["data"]["match"] == "ambiguous"
        assert len(out["data"]["candidates"]) == 2
        assert out["data"]["verified"] is None

    def test_active_company_happy_path(self):
        from verify.company import verify_company
        db = _mock_db(
            entity=ENTITY,
            profile=_ns(lifecycle_stage="growing", f_skatt_active_at="2008-01-01",
                        f_skatt_revoked_at=None, ownership_changes_12m=0,
                        ownership_last_change_at=None, kreditvakt_scored_at=None),
            konkurs_rows=[],
            kron=_ns(cases_last_6mo=0, latest_filed=None, total_active_claim_sek=None),
            tax=None,
            score=_ns(risk_band=1, distress_probability=0.02,
                      scored_at=datetime.now(timezone.utc), score_source="live"),
            changes=[_ns(snapshot_date="2026-09-01", field_name="street",
                         old_value="A", new_value="B")],
            pipelines=[_ns(pipeline="bolagsverket_bulk",
                           last_success=datetime.now(timezone.utc),
                           last_attempt=datetime.now(timezone.utc))],
        )
        out = verify_company(db, "5567037485")
        d = out["data"]
        assert d["found"] is True
        assert d["verified"] is True
        assert d["identity"]["name"] == "Spotify AB"
        assert d["legal_status"]["status"] == "active"
        assert d["registrations"]["f_tax"]["status"] == "active"
        assert d["registrations"]["vat"]["status"] == "not_tracked"
        assert d["insolvency"]["in_konkurs"] is False
        assert d["risk"]["risk_tier"] == "HEALTHY"
        assert d["latest_changes"][0]["field"] == "street"
        assert "bolagsverket_bulk" in d["sources"]
        assert out["confidence"] == 0.95
        assert out["warnings"] == []

    def test_konkurs_flag_raises_signal(self):
        from verify.company import verify_company
        db = _mock_db(
            entity=ENTITY,
            konkurs_rows=[_ns(case_ref="bv-konkurs-x-2026-01-01",
                              filed_at="2026-01-01", status_code="KK-AVOMFO",
                              is_active=True, resolved_at=None)],
            kron=_ns(cases_last_6mo=2, latest_filed="2026-08-01",
                     total_active_claim_sek=50000),
        )
        out = verify_company(db, "556703-7485")
        assert out["data"]["insolvency"]["in_konkurs"] is True
        assert out["data"]["insolvency"]["kronofogden_cases_6m"] == 2
        keys = {s["key"] for s in out["signals"]}
        assert "in_konkurs" in keys and "kronofogden_count" in keys

    def test_deregistered_company_not_verified(self):
        from verify.company import verify_company
        dead = _ns(**{**ENTITY.__dict__, "is_active": False,
                      "deregistered_at": "2025-12-01"})
        db = _mock_db(entity=dead)
        out = verify_company(db, "556703-7485")
        assert out["data"]["verified"] is False
        assert out["data"]["legal_status"]["status"] == "deregistered"

    def test_optional_source_failure_degrades_with_warning(self):
        from verify.company import verify_company
        db = _mock_db(entity=ENTITY)

        def boom(query, params=None):
            sql = str(query)
            if "norric_entities" in sql:
                r = MagicMock()
                r.fetchone.return_value = ENTITY
                return r
            raise RuntimeError("table missing")
        db.execute.side_effect = boom
        out = verify_company(db, "556703-7485")
        assert out["data"]["found"] is True
        assert out["data"]["risk"] is None
        assert any("company_scores" in w for w in out["warnings"])
