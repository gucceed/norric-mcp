"""Regression test for the kill-mock contract.

Originally specced (kill-mock prompt, task 5) to hit /api/score/{orgnr}
against a seeded test DB for IKEA / H&M / Telia and assert:
  - score_source != "mock"
  - name matches norric_entities
  - H&M's and Telia's names differ (fixture-collision regression)

A seeded test DB is not part of this repo's infrastructure today, so this
file enforces the same contract at the function boundary instead:

  1. The scorer's no-signals path returns score_source='no_signals',
     never 'mock'.
  2. The scorer's no-signals result has no fabricated company_name.
  3. The exported risk_tier vocabulary matches the locked contract.
  4. risk_score / risk_band map deterministically and per-band.

The HTTP-level test (TestClient + seeded entities/payment_signals rows)
should land as a follow-up once a tests/conftest.py with a Postgres
fixture exists.
"""

import pytest

from scoring.kreditvakt import (
    TIER_FROM_BAND,
    _no_signals_result,
    _risk_score_from_band,
)

CONTRACT_TIERS = {"HEALTHY", "WATCH", "ELEVATED", "HIGH", "CRITICAL"}
ALLOWED_SCORE_SOURCES = {"live", "no_signals"}


@pytest.mark.parametrize("orgnr", ["556074-7551", "556151-2376", "556430-0142"])
def test_no_signals_result_never_returns_mock(orgnr: str) -> None:
    result = _no_signals_result(orgnr)
    assert result["score_source"] == "no_signals"
    assert result["score_source"] != "mock"
    assert result["score_source"] in ALLOWED_SCORE_SOURCES


@pytest.mark.parametrize("orgnr", ["556074-7551", "556151-2376", "556430-0142"])
def test_no_signals_result_has_no_fabricated_fields(orgnr: str) -> None:
    result = _no_signals_result(orgnr)
    # The mock fabricator used to fill these — they must not appear.
    assert "company_name" not in result
    assert "industry" not in result
    # Risk fields must be null when no signals exist.
    assert result["risk_score"] is None
    assert result["risk_band"] is None
    assert result["risk_tier"] is None
    assert result["distress_probability"] is None
    assert result["signals"] == []


def test_risk_tier_vocabulary_locked() -> None:
    assert set(TIER_FROM_BAND.values()) == CONTRACT_TIERS
    # Ascending bands map to ascending-severity tiers
    assert TIER_FROM_BAND[1] == "HEALTHY"
    assert TIER_FROM_BAND[5] == "CRITICAL"


def test_risk_score_per_band_deterministic() -> None:
    # The 0-20 score family must produce a stable, ascending mapping.
    scores = [_risk_score_from_band(b) for b in (1, 2, 3, 4, 5)]
    assert scores == sorted(scores)
    assert min(scores) >= 0 and max(scores) <= 20


def test_no_signals_result_distinct_orgnrs_dont_collide() -> None:
    """Regression for the H&M/Telia 'Central Teknik AB' collision.

    With fabrication removed, distinct orgnrs produce structurally identical
    no-signal results — but neither carries a fabricated name. Asserts the
    intentional shape; the collision bug is impossible because there are no
    name strings to collide on.
    """
    hm    = _no_signals_result("556151-2376")
    telia = _no_signals_result("556430-0142")
    assert hm["orgnr"] != telia["orgnr"]
    assert "company_name" not in hm
    assert "company_name" not in telia
