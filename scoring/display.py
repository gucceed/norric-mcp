"""
scoring/display.py

Pure read-only display transform for Kreditvakt scores.

The internal model (distress_probability [0.0, 1.0]) is FROZEN.
This module only transforms for display — it never feeds back into scoring.

DisplayScore fields:
  display_score  int [0–20]       — the customer-facing score
  band           int [1–5]        — risk band
  band_label     str              — Swedish label
  band_action    str              — Swedish recommended action
  internal_score int [0–100]      — passthrough alias (deprecated, sunset 2027-05)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Hysteresis: internal score must cross band boundary by this many
# distress_probability points before displayed band moves.
HYSTERESIS_THRESHOLD = 0.03  # 3 points on 0–100 scale = 0.03 on [0.0, 1.0]

# Band boundaries on distress_probability.
#
# Convention: boundaries are LOWER-INCLUSIVE / UPPER-EXCLUSIVE.
# The boundary value belongs to the UPPER (higher-risk) band.
#
#   Band 1 (Stabil):        0.00 ≤ p < 0.20   display 0–3
#   Band 2 (Bevaka):        0.20 ≤ p < 0.40   display 4–7
#   Band 3 (Förhöjd risk):  0.40 ≤ p < 0.60   display 8–11
#   Band 4 (Kräv säkerhet): 0.60 ≤ p < 0.80   display 12–15
#   Band 5 (Stoppa):        0.80 ≤ p ≤ 1.00   display 16–20
#
# Example: distress_probability=0.20 → band 2, not band 1.
# This matches UC/Creditsafe convention (≥ boundary → higher band).
# All API documentation and OpenAPI field descriptions must state this
# convention explicitly.
_BAND_BOUNDARIES = [0.20, 0.40, 0.60, 0.80]

_BAND_LABELS = {
    1: "Stabil",
    2: "Bevaka",
    3: "Förhöjd risk",
    4: "Kräv säkerhet",
    5: "Stoppa krediter",
}

_BAND_ACTIONS = {
    1: "Inga åtgärder krävs.",
    2: "Monitorera kvartalsvis. Förstärk inte krediten utan ny utvärdering.",
    3: "Begränsa nya kreditlinjer. Begär uppdaterade ekonomiska underlag.",
    4: "Befintliga relationer endast med personlig borgen eller fakturapant. Stoppa nya kreditlinjer.",
    5: "Akut. Stoppa utgående krediter. Påbörja indrivning. Konkurs sannolik inom 90 dagar.",
}


@dataclass(frozen=True)
class DisplayScore:
    display_score: int          # [0, 20]
    band: int                   # [1, 5]
    band_label: str
    band_action: str
    internal_score: int         # [0, 100] — deprecated alias, sunset 2027-05


def _natural_band(distress_probability: float) -> int:
    """Compute band from distress_probability without hysteresis."""
    for band, boundary in enumerate(_BAND_BOUNDARIES, start=1):
        if distress_probability < boundary:
            return band
    return 5


def to_display(
    distress_probability: float,
    last_displayed_band: Optional[int] = None,
) -> tuple[DisplayScore, int]:
    """
    Transform distress_probability into a DisplayScore, applying hysteresis.

    Args:
        distress_probability: [0.0, 1.0] from the frozen scorer
        last_displayed_band:  previously shown band (None on first run)

    Returns:
        (DisplayScore, new_displayed_band)
        new_displayed_band is what to persist back to company_scores.
    """
    p = max(0.0, min(1.0, distress_probability))

    natural = _natural_band(p)

    _EPS = 1e-9  # guard against float addition imprecision (e.g. 0.40+0.03 = 0.43000…5)

    if last_displayed_band is None or last_displayed_band == natural:
        displayed_band = natural
    elif natural > last_displayed_band:
        # Score moved up — only move band if it has cleared the boundary by >= threshold
        boundary = _BAND_BOUNDARIES[last_displayed_band - 1]  # upper boundary of current band
        displayed_band = natural if p >= boundary + HYSTERESIS_THRESHOLD - _EPS else last_displayed_band
    else:
        # Score moved down — only move band if it has cleared the boundary by >= threshold
        boundary = _BAND_BOUNDARIES[natural - 1]  # upper boundary of target band
        displayed_band = natural if p < boundary - HYSTERESIS_THRESHOLD + _EPS else last_displayed_band

    display_score = min(20, max(0, round(p * 20)))

    score = DisplayScore(
        display_score=display_score,
        band=displayed_band,
        band_label=_BAND_LABELS[displayed_band],
        band_action=_BAND_ACTIONS[displayed_band],
        internal_score=round(p * 100),
    )
    return score, displayed_band
