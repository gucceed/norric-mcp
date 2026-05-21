"""Unit tests for kreditvakt.contagion — proximity hierarchy, the band gate
that restricts contagion analysis to HIGH/CRITICAL, and the disclaimer the
MCP tool surfaces on every response."""

from kreditvakt.contagion import (
    CONTAGION_BANDS,
    PROXIMITY,
    SCORE_FROM_BAND,
    TIER_FROM_BAND,
)


def test_proximity_score_ordering():
    """Same kommunkod > same county. Tighter geography = higher proximity."""
    assert PROXIMITY["same_sector_kommunkod"] > PROXIMITY["same_sector_county"]
    assert PROXIMITY["same_sector_kommunkod"] == 1.0
    assert PROXIMITY["same_sector_county"]    == 0.7
    # All proximity scores are valid weights in [0, 1].
    for reason, score in PROXIMITY.items():
        assert 0.0 <= score <= 1.0, f"{reason} proximity out of range: {score}"


def test_contagion_only_for_high_critical():
    """Contagion analysis only runs for band >= 4 (HIGH / CRITICAL)."""
    assert set(CONTAGION_BANDS) == {4, 5}
    assert TIER_FROM_BAND[4] == "HIGH"
    assert TIER_FROM_BAND[5] == "CRITICAL"
    # Bands 1–3 must NOT be in the contagion set.
    for band in (1, 2, 3):
        assert band not in CONTAGION_BANDS, (
            f"band {band} ({TIER_FROM_BAND[band]}) should not trigger contagion"
        )
    # Score map must be aligned with scoring.kreditvakt._risk_score_from_band.
    assert SCORE_FROM_BAND == {1: 2, 2: 6, 3: 10, 4: 14, 5: 18}


def test_response_includes_disclaimer():
    """The MCP tool's response always carries the probabilistic disclaimer."""
    # Import here so the test does not pay the import cost at module load.
    from server import _CONTAGION_DISCLAIMER

    assert "probabilistic" in _CONTAGION_DISCLAIMER.lower()
    assert "not verified" in _CONTAGION_DISCLAIMER.lower()
    # The disclaimer must reference what the match is based on so a reader
    # understands the limitation without external documentation.
    assert "sector" in _CONTAGION_DISCLAIMER.lower()
    assert "geograph" in _CONTAGION_DISCLAIMER.lower()
