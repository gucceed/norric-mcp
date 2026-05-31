"""Locks the public /score response contract produced by
kreditvakt.api._enrich_response — the canonical risk_score/risk_band/risk_tier
envelope. Complements the function-boundary checks in
test_no_fabrication_response.py (which cover the scorer's own output).
"""
import pytest

pytest.importorskip("fastapi")  # api module constructs a FastAPI app at import

try:
    from kreditvakt.api import _enrich_response
except Exception as exc:  # pragma: no cover - env without full app deps
    pytest.skip(f"kreditvakt.api not importable here: {exc}", allow_module_level=True)

CONTRACT_TIERS = {"HEALTHY", "WATCH", "ELEVATED", "HIGH", "CRITICAL"}


def _live_result(orgnr: str = "556677-8899") -> dict:
    """A 'live' scorer result mirroring scoring.kreditvakt.score_from_db()."""
    return {
        "orgnr": orgnr,
        "score_source": "live",
        "distress_probability": 0.42,
        "risk_band": 3,
        "risk_score": 10,
        "risk_tier": "ELEVATED",
        "insolvency_score": 42,
        "signals": [{"key": "konkurs_petition", "value": True}],
        "signals_fired": 1,
        "signals_total": 5,
        "scored_at": "2026-05-31T00:00:00+00:00",
        "data_freshness_hours": 12.0,
        "stale_data": False,
    }


def test_live_envelope_is_canonical() -> None:
    out = _enrich_response(_live_result(), None, entity={"name": "Acme AB", "status": "active"})

    # Canonical risk family, in-range.
    assert out["risk_score"] == 10 and 0 <= out["risk_score"] <= 20
    assert out["risk_band"] == 3 and 1 <= out["risk_band"] <= 5
    assert out["risk_tier"] in CONTRACT_TIERS

    # Envelope metadata.
    assert out["scale"] == "0-20"
    assert out["polarity"] == "ascending_risk"
    assert out["score_source"] == "live"

    # Legacy / marketing vocab must NOT leak into the public envelope.
    assert "insolvency_score" not in out
    assert "display_score" not in out
    assert "band_label" not in out


def test_no_signals_envelope_nulls_risk_and_keeps_ingestion_status() -> None:
    res = {
        "orgnr": "556000-0000",
        "score_source": "no_signals",
        "distress_probability": None,
        "risk_band": None,
        "risk_score": None,
        "risk_tier": None,
        "signals": [],
        "signals_fired": 0,
        "signals_total": 5,
        "scored_at": "2026-05-31T00:00:00+00:00",
        "data_freshness_hours": None,
        "stale_data": False,
        "ingestion_status": {"bolagsverket": "see_pipeline_runs"},
    }
    out = _enrich_response(res, None, entity=None)

    assert out["risk_score"] is None
    assert out["risk_band"] is None
    assert out["risk_tier"] is None
    assert out["score_source"] == "no_signals"
    assert out["ingestion_status"] == {"bolagsverket": "see_pipeline_runs"}
