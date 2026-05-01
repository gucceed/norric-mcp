"""
Tests for scoring/display.py

Coverage:
  - Band boundary correctness (all 4 boundaries)
  - Display score formula
  - Hysteresis: 12 targeted cases
  - Edge cases: 0.0, 1.0, clamp behaviour
"""

import pytest
from scoring.display import to_display, _natural_band, HYSTERESIS_THRESHOLD


# ── Natural band mapping ──────────────────────────────────────────────────────

class TestNaturalBand:
    def test_band_1_low(self):
        assert _natural_band(0.00) == 1

    def test_band_1_top(self):
        assert _natural_band(0.199) == 1

    def test_band_2_at_boundary(self):
        assert _natural_band(0.20) == 2

    def test_band_2_top(self):
        assert _natural_band(0.399) == 2

    def test_band_3_at_boundary(self):
        assert _natural_band(0.40) == 3

    def test_band_3_top(self):
        assert _natural_band(0.599) == 3

    def test_band_4_at_boundary(self):
        assert _natural_band(0.60) == 4

    def test_band_4_top(self):
        assert _natural_band(0.799) == 4

    def test_band_5_at_boundary(self):
        assert _natural_band(0.80) == 5

    def test_band_5_max(self):
        assert _natural_band(1.00) == 5


# ── Display score formula ─────────────────────────────────────────────────────

class TestDisplayScore:
    def test_zero(self):
        ds, _ = to_display(0.0)
        assert ds.display_score == 0
        assert ds.band == 1

    def test_one(self):
        ds, _ = to_display(1.0)
        assert ds.display_score == 20
        assert ds.band == 5

    def test_boundary_020_is_band_1(self):
        # 0.20 is the start of band 2 — but display_score = round(0.20 * 20) = 4
        # band must be 2 (natural band at 0.20 is 2)
        ds, _ = to_display(0.20)
        assert ds.display_score == 4
        assert ds.band == 2

    def test_0199_is_band_1(self):
        # Just below boundary — must be band 1
        ds, _ = to_display(0.199)
        assert ds.band == 1

    def test_050(self):
        ds, _ = to_display(0.50)
        assert ds.display_score == 10
        assert ds.band == 3

    def test_internal_score_alias(self):
        ds, _ = to_display(0.75)
        assert ds.internal_score == 75

    def test_clamp_above_one(self):
        ds, _ = to_display(1.5)
        assert ds.display_score == 20

    def test_clamp_below_zero(self):
        ds, _ = to_display(-0.1)
        assert ds.display_score == 0

    def test_band_labels_present(self):
        for p in [0.1, 0.3, 0.5, 0.7, 0.9]:
            ds, _ = to_display(p)
            assert ds.band_label
            assert ds.band_action


# ── Hysteresis ────────────────────────────────────────────────────────────────
#
# Each boundary (0.20, 0.40, 0.60, 0.80) gets three cases:
#   A) within-band move — no transition expected
#   B) crossing boundary without sufficient overshoot — band holds
#   C) crossing boundary with sufficient overshoot — band moves
#
# Threshold = 0.03

class TestHysteresis:

    # ── Boundary 0.20 (band 1 → 2) ───────────────────────────────────────────

    def test_b020_A_within_band_no_change(self):
        """Company in band 1, score stays in band 1 — no transition."""
        ds, new_band = to_display(0.15, last_displayed_band=1)
        assert new_band == 1

    def test_b020_B_crosses_without_overshoot(self):
        """Score crosses 0.20 but not by >=0.03 — band must hold at 1."""
        # Natural band at 0.22 is 2, but 0.22 < 0.20 + 0.03 = 0.23
        ds, new_band = to_display(0.22, last_displayed_band=1)
        assert new_band == 1

    def test_b020_C_crosses_with_overshoot(self):
        """Score crosses 0.20 by >=0.03 — band must move to 2."""
        # 0.23 >= 0.20 + 0.03
        ds, new_band = to_display(0.23, last_displayed_band=1)
        assert new_band == 2

    # ── Boundary 0.40 (band 2 → 3) ───────────────────────────────────────────

    def test_b040_A_within_band_no_change(self):
        """Company in band 2, score stays in band 2 — no transition."""
        ds, new_band = to_display(0.35, last_displayed_band=2)
        assert new_band == 2

    def test_b040_B_crosses_without_overshoot(self):
        """Score crosses 0.40 but 0.42 < 0.40 + 0.03 = 0.43 — band holds."""
        ds, new_band = to_display(0.42, last_displayed_band=2)
        assert new_band == 2

    def test_b040_C_crosses_with_overshoot(self):
        """Score 0.43 >= 0.40 + 0.03 — band moves to 3."""
        ds, new_band = to_display(0.43, last_displayed_band=2)
        assert new_band == 3

    # ── Boundary 0.60 (band 3 → 4) ───────────────────────────────────────────

    def test_b060_A_within_band_no_change(self):
        ds, new_band = to_display(0.55, last_displayed_band=3)
        assert new_band == 3

    def test_b060_B_crosses_without_overshoot(self):
        """Score 0.62 < 0.60 + 0.03 = 0.63 — band holds at 3."""
        ds, new_band = to_display(0.62, last_displayed_band=3)
        assert new_band == 3

    def test_b060_C_crosses_with_overshoot(self):
        """Score 0.63 >= 0.60 + 0.03 — band moves to 4."""
        ds, new_band = to_display(0.63, last_displayed_band=3)
        assert new_band == 4

    # ── Boundary 0.80 (band 4 → 5) ───────────────────────────────────────────

    def test_b080_A_within_band_no_change(self):
        ds, new_band = to_display(0.75, last_displayed_band=4)
        assert new_band == 4

    def test_b080_B_crosses_without_overshoot(self):
        """Internal=0.78 → natural band 4, but was already in band 4. No change."""
        # Actually let's test: company in band 4, score goes to 0.82 (band 5)
        # but 0.82 < 0.80 + 0.03 = 0.83 → holds
        ds, new_band = to_display(0.82, last_displayed_band=4)
        assert new_band == 4

    def test_b080_C_crosses_with_overshoot(self):
        """Score 0.83 >= 0.80 + 0.03 — band moves to 5."""
        ds, new_band = to_display(0.83, last_displayed_band=4)
        assert new_band == 5

    # ── Additional hysteresis: downward movement ──────────────────────────────

    def test_downward_without_overshoot_holds(self):
        """Company in band 3. Score drops to 0.38 (band 2 natural).
        0.38 is not < 0.40 - 0.03 = 0.37 — band holds at 3."""
        ds, new_band = to_display(0.38, last_displayed_band=3)
        assert new_band == 3

    def test_downward_with_overshoot_moves(self):
        """Company in band 3. Score drops to 0.36 < 0.40 - 0.03 = 0.37 — band moves to 2."""
        ds, new_band = to_display(0.36, last_displayed_band=3)
        assert new_band == 2

    def test_first_run_no_hysteresis(self):
        """last_displayed_band=None → natural band used directly."""
        ds, new_band = to_display(0.78, last_displayed_band=None)
        assert new_band == 4
        assert ds.band == 4

    def test_same_band_no_update(self):
        """Score stays within same band — new_band equals old band."""
        ds, new_band = to_display(0.50, last_displayed_band=3)
        assert new_band == 3
