"""Unit tests for kreditvakt.signal_cross — pure-function coverage of the
band→score map, score→tier thresholds, and tier ordering used for
escalation detection."""

from kreditvakt.signal_cross import BAND_TO_SCORE, TIER_ORDER, score_to_tier


def test_score_to_tier():
    assert score_to_tier(0)  == "LOW"
    assert score_to_tier(7)  == "LOW"
    assert score_to_tier(8)  == "MEDIUM"
    assert score_to_tier(12) == "MEDIUM"
    assert score_to_tier(13) == "HIGH"
    assert score_to_tier(16) == "HIGH"
    assert score_to_tier(17) == "CRITICAL"
    assert score_to_tier(20) == "CRITICAL"


def test_band_to_score():
    for band in [1, 2, 3, 4, 5]:
        score = BAND_TO_SCORE[band]
        assert 0 <= score <= 20
        assert score_to_tier(score) in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def test_tier_escalation_order():
    assert TIER_ORDER.index("MEDIUM")   > TIER_ORDER.index("LOW")
    assert TIER_ORDER.index("HIGH")     > TIER_ORDER.index("MEDIUM")
    assert TIER_ORDER.index("CRITICAL") > TIER_ORDER.index("HIGH")
