"""
Tests for scoring/kreditvakt.py — Tier 2 Kreditvakt scorer.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


def _mock_db(tax_row=None, kron_row=None, konkurs_row=None):
    """Build a mock DB session with configurable query results."""
    db = MagicMock()

    call_count = {"n": 0}

    def execute_side_effect(query, params=None):
        sql = str(query).lower()
        result = MagicMock()

        if "norric_tax_signals" in sql:
            result.fetchone.return_value = tax_row
        elif "norric_payment_signals" in sql and "konkurs" in sql:
            result.fetchone.return_value = konkurs_row
        elif "norric_payment_signals" in sql:
            result.fetchone.return_value = kron_row
        else:
            result.fetchone.return_value = None

        return result

    db.execute.side_effect = execute_side_effect
    db.commit = MagicMock()
    return db


class TestBandMapping:
    def test_band_1_minimal(self):
        from scoring.kreditvakt import _band
        assert _band(0.0) == 1
        assert _band(0.09) == 1

    def test_band_2_low(self):
        from scoring.kreditvakt import _band
        assert _band(0.10) == 2
        assert _band(0.24) == 2

    def test_band_3_elevated(self):
        from scoring.kreditvakt import _band
        assert _band(0.25) == 3
        assert _band(0.49) == 3

    def test_band_4_high(self):
        from scoring.kreditvakt import _band
        assert _band(0.50) == 4
        assert _band(0.74) == 4

    def test_band_5_critical(self):
        from scoring.kreditvakt import _band
        assert _band(0.75) == 5
        assert _band(1.0) == 5


class TestScoreFromDb:
    def test_no_signals_falls_back_to_mock(self):
        """When no live signals, score_source must be 'mock'."""
        from scoring.kreditvakt import score_from_db

        kron_row = MagicMock()
        kron_row.case_count = 0
        kron_row.cases_last_6mo = 0
        kron_row.latest_filed = None
        kron_row.days_since_last = None
        kron_row.total_claim_sek = 0

        db = _mock_db(tax_row=None, kron_row=kron_row, konkurs_row=None)

        with patch("scoring.kreditvakt._mock_fallback") as mock_fb:
            mock_fb.return_value = {"score_source": "mock", "orgnr": "556000-0001"}
            result = score_from_db(db, "556000-0001")
            mock_fb.assert_called_once_with("556000-0001")

    def test_live_tax_signal_produces_band(self):
        """With a tax signal, should produce a live score with band >= 2."""
        from scoring.kreditvakt import score_from_db

        tax_row = MagicMock()
        tax_row.amount_sek = 500_000
        tax_row.last_seen_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        tax_row.is_active = True

        kron_row = MagicMock()
        kron_row.case_count = 0
        kron_row.cases_last_6mo = 0
        kron_row.latest_filed = None
        kron_row.days_since_last = None
        kron_row.total_claim_sek = 0

        db = _mock_db(tax_row=tax_row, kron_row=kron_row, konkurs_row=None)
        result = score_from_db(db, "556000-0001")

        assert result["score_source"] == "live"
        assert result["risk_band"] >= 2
        assert result["distress_probability"] > 0.0
        assert 0.0 <= result["distress_probability"] <= 1.0
        assert result["skatteverket_flag"] is True
        assert result["skuld_sek"] == 500_000

    def test_high_debt_produces_band_3_or_higher(self):
        """2.5M SEK tax debt should push into band 3+."""
        from scoring.kreditvakt import score_from_db

        tax_row = MagicMock()
        tax_row.amount_sek = 2_500_000
        tax_row.last_seen_at = datetime(2026, 4, 20, tzinfo=timezone.utc)
        tax_row.is_active = True

        kron_row = MagicMock()
        kron_row.case_count = 0
        kron_row.cases_last_6mo = 0
        kron_row.latest_filed = None
        kron_row.days_since_last = None
        kron_row.total_claim_sek = 0

        db = _mock_db(tax_row=tax_row, kron_row=kron_row, konkurs_row=None)
        result = score_from_db(db, "556000-0002")

        assert result["risk_band"] >= 3

    def test_konkurs_petition_fires_signal(self):
        """Konkursansökan should be reflected in signals list."""
        from scoring.kreditvakt import score_from_db

        tax_row = MagicMock()
        tax_row.amount_sek = 100_000
        tax_row.last_seen_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        tax_row.is_active = True

        kron_row = MagicMock()
        kron_row.case_count = 3
        kron_row.cases_last_6mo = 3
        kron_row.latest_filed = "2026-03-01"
        kron_row.days_since_last = 60
        kron_row.total_claim_sek = 200_000

        konkurs_row = MagicMock()  # non-None = petition exists

        db = _mock_db(tax_row=tax_row, kron_row=kron_row, konkurs_row=konkurs_row)
        result = score_from_db(db, "556000-0003")

        keys = {s["key"] for s in result["signals"]}
        assert "konkurs_petition" in keys
        assert result["bolagsverket_petition"] is True

    def test_distress_probability_bounded(self):
        """distress_probability must always be in [0.0, 1.0]."""
        from scoring.kreditvakt import score_from_db

        tax_row = MagicMock()
        tax_row.amount_sek = 99_000_000  # extreme value
        tax_row.last_seen_at = datetime(2026, 4, 27, tzinfo=timezone.utc)
        tax_row.is_active = True

        kron_row = MagicMock()
        kron_row.case_count = 999
        kron_row.cases_last_6mo = 50
        kron_row.latest_filed = "2026-04-25"
        kron_row.days_since_last = 2
        kron_row.total_claim_sek = 5_000_000

        konkurs_row = MagicMock()

        db = _mock_db(tax_row=tax_row, kron_row=kron_row, konkurs_row=konkurs_row)
        result = score_from_db(db, "556999-9999")

        assert 0.0 <= result["distress_probability"] <= 1.0
        assert result["risk_band"] == 5

    def test_orgnr_normalised(self):
        """Orgnr without dash should be accepted and normalised."""
        from scoring.kreditvakt import score_from_db

        kron_row = MagicMock()
        kron_row.case_count = 0
        kron_row.cases_last_6mo = 0
        kron_row.latest_filed = None
        kron_row.days_since_last = None
        kron_row.total_claim_sek = 0

        db = _mock_db(tax_row=None, kron_row=kron_row, konkurs_row=None)

        with patch("scoring.kreditvakt._mock_fallback") as mock_fb:
            mock_fb.return_value = {"score_source": "mock", "orgnr": "556012-3456"}
            score_from_db(db, "5560123456")
            called_orgnr = mock_fb.call_args[0][0]
            assert called_orgnr == "556012-3456"


class TestMockFallback:
    def test_mock_fallback_returns_valid_structure(self):
        from scoring.kreditvakt import _mock_fallback
        result = _mock_fallback("556000-0001")
        assert "distress_probability" in result
        assert "risk_band" in result
        assert result["score_source"] == "mock"
        assert result["stale_data"] is True
        assert 0.0 <= result["distress_probability"] <= 1.0
        assert 1 <= result["risk_band"] <= 5

    def test_mock_fallback_consistent(self):
        """Same orgnr should always return same result (deterministic)."""
        from scoring.kreditvakt import _mock_fallback
        r1 = _mock_fallback("556123-4567")
        r2 = _mock_fallback("556123-4567")
        assert r1["distress_probability"] == r2["distress_probability"]
        assert r1["risk_band"] == r2["risk_band"]
