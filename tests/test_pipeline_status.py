from datetime import datetime, timezone, timedelta

from core.pipeline_status import agency_for_pipeline, summarize, age_days


def test_pipeline_mapping():
    assert agency_for_pipeline("bolagsverket_bulk") == "bolagsverket"
    assert agency_for_pipeline("bolagsverket_konkurs") == "bolagsverket"
    assert agency_for_pipeline("scb_TAB_1") == "scb"
    assert agency_for_pipeline("brreg_bulk") is None


def test_summarize_takes_newest_success_per_agency():
    now = datetime.now(timezone.utc)
    out = summarize([
        ("bolagsverket_bulk", now - timedelta(days=2), 3),
        ("bolagsverket_konkurs", now - timedelta(hours=1), 5),
        ("brreg_bulk", now, 1),
        ("kronofogden_betalning", None, 0),
    ])
    assert set(out) == {"bolagsverket"}
    assert out["bolagsverket"]["success_runs"] == 8
    assert age_days(out["bolagsverket"]["last_success"]) == 0
