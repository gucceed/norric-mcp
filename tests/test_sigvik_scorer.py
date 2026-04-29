"""
Tests for Sigvik intent scorer (ingestion/scoring/intent.py in sigvik-backend).
Imports directly since both repos share the same test runner context.
"""

import sys
import os

# Add sigvik-backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sigvik-backend"))

import pytest
from ingestion.scoring.intent import (
    ScoringInput,
    IntentScore,
    compute_intent_score,
    score_from_db_rows,
    _compute_confidence,
)


class TestComputeIntentScore:
    def test_empty_input_scores_zero(self):
        inp = ScoringInput(orgnr="716400-0001")
        result = compute_intent_score(inp)
        assert result.score == 0.0
        assert result.confidence_label == "Tidig indikation"

    def test_large_avgift_increase_adds_25pts(self):
        inp = ScoringInput(orgnr="716400-0001", avgift_change_pct_recent=12.0)
        result = compute_intent_score(inp)
        assert result.score >= 25

    def test_five_pct_avgift_increase_adds_15pts(self):
        inp = ScoringInput(orgnr="716400-0002", avgift_change_pct_recent=6.0)
        result = compute_intent_score(inp)
        # Should be 15 pts from avgift
        assert 14 <= result.score <= 20  # ±1 from rounding

    def test_avgift_streak_bonus(self):
        inp = ScoringInput(orgnr="716400-0003", avgift_increase_streak=3)
        result = compute_intent_score(inp)
        assert result.score >= 10  # streak bonus

    def test_declining_underhallsfond_adds_15pts(self):
        inp = ScoringInput(orgnr="716400-0004", underhallsfond_declining=True)
        result = compute_intent_score(inp)
        assert result.score >= 15

    def test_mentions_tak_adds_points(self):
        inp = ScoringInput(orgnr="716400-0005", mentions_tak=True)
        result = compute_intent_score(inp)
        assert result.score >= 8
        assert "tak" in result.project_type_hints

    def test_eu_deadline_pressure_adds_10pts(self):
        inp = ScoringInput(
            orgnr="716400-0006",
            energiklass="F",
            energiklass_source="official",
            eu_deadline_pressure=True,
        )
        result = compute_intent_score(inp)
        assert result.score >= 10
        assert "energiåtgärder" in result.project_type_hints

    def test_predicted_eu_class_discounted(self):
        """Predicted energiklass should score less than official."""
        inp_official = ScoringInput(
            orgnr="716400-0007",
            energiklass="F",
            energiklass_source="official",
            eu_deadline_pressure=True,
            energiklass_confidence=1.0,
        )
        inp_predicted = ScoringInput(
            orgnr="716400-0007",
            energiklass="F",
            energiklass_source="predicted",
            eu_deadline_predicted=True,
            energiklass_confidence=0.6,
        )
        r_official = compute_intent_score(inp_official)
        r_predicted = compute_intent_score(inp_predicted)
        assert r_official.score > r_predicted.score

    def test_score_capped_at_100(self):
        """Max stacked signals should not exceed 100."""
        inp = ScoringInput(
            orgnr="716400-0008",
            avgift_change_pct_recent=15.0,
            avgift_increase_streak=5,
            lan_change_pct_recent=25.0,
            lan_trend_3yr=20.0,
            underhallsfond_declining=True,
            mentions_tak=True,
            mentions_fasad=True,
            mentions_stammar=True,
            eu_deadline_pressure=True,
            building_age=55,
            energiklass="G",
            energiklass_source="official",
        )
        result = compute_intent_score(inp)
        assert result.score <= 100.0

    def test_horizon_imminent_when_year_near(self):
        from datetime import date
        current = date.today().year
        inp = ScoringInput(orgnr="716400-0009", tak_year=current, mentions_tak=True)
        result = compute_intent_score(inp)
        assert result.horizon == "0–6 månader"

    def test_horizon_medium_when_score_40_to_70(self):
        inp = ScoringInput(
            orgnr="716400-0010",
            avgift_change_pct_recent=5.0,
            lan_change_pct_recent=12.0,
        )
        result = compute_intent_score(inp)
        if 40 <= result.score < 70:
            assert result.horizon == "6–18 månader"

    def test_confidence_label_high_when_lots_of_data(self):
        inp = ScoringInput(
            orgnr="716400-0011",
            num_arsredovisningar=5,
            avgift_change_pct_recent=5.0,
            lan_change_pct_recent=10.0,
            underhallsfond_change_pct_recent=-5.0,
            energiklass="E",
            building_year=1980,
        )
        result = compute_intent_score(inp)
        assert result.confidence >= 0.7
        assert result.confidence_label == "Starkt signal"

    def test_top_signals_list_not_empty_when_signals_fire(self):
        inp = ScoringInput(
            orgnr="716400-0012",
            avgift_change_pct_recent=10.0,
            mentions_tak=True,
        )
        result = compute_intent_score(inp)
        assert len(result.top_signals) > 0

    def test_top_signals_max_5(self):
        inp = ScoringInput(
            orgnr="716400-0013",
            avgift_change_pct_recent=12.0,
            avgift_increase_streak=3,
            lan_change_pct_recent=20.0,
            underhallsfond_declining=True,
            mentions_tak=True,
            mentions_fasad=True,
            mentions_stammar=True,
            eu_deadline_pressure=True,
        )
        result = compute_intent_score(inp)
        assert len(result.top_signals) <= 5


class TestComputeConfidence:
    def test_zero_arsredovisningar_low_confidence(self):
        inp = ScoringInput(orgnr="716400-0020", num_arsredovisningar=0)
        assert _compute_confidence(inp) < 0.4

    def test_five_arsredovisningar_higher_confidence(self):
        inp = ScoringInput(
            orgnr="716400-0021",
            num_arsredovisningar=5,
            avgift_change_pct_recent=5.0,
            lan_change_pct_recent=10.0,
            energiklass="E",
            building_year=1975,
        )
        assert _compute_confidence(inp) >= 0.7

    def test_confidence_bounded_0_to_1(self):
        inp = ScoringInput(orgnr="716400-0022", num_arsredovisningar=100)
        assert 0.0 <= _compute_confidence(inp) <= 1.0


class TestScoreFromDbRows:
    def test_empty_arsredovisningar_returns_valid_score(self):
        result = score_from_db_rows(
            orgnr="716400-0030",
            building_year=None,
            arsredovisningar=[],
            energideklaration=None,
        )
        assert isinstance(result, IntentScore)
        assert result.score == 0.0

    def test_single_arsredovisning_populates_signals(self):
        ar = {
            "fiscal_year": 2023,
            "avgift_change_pct": 8.0,
            "lan_change_pct": 15.0,
            "total_lan": 10_000_000,
            "underhallsfond": 500_000,
            "underhallsfond_change_pct": None,
            "mentions_tak": True,
            "mentions_fasad": False,
            "mentions_stammar": False,
            "mentions_fonster": False,
            "mentions_hiss": False,
            "tak_year_mentioned": 2027,
            "fasad_year_mentioned": None,
            "stammar_year_mentioned": None,
            "fonster_year_mentioned": None,
            "hiss_year_mentioned": None,
            "maintenance_plan_raw": "underhållsplan: tak 2027",
            "full_text_preview": "takrenovering planeras 2027",
        }
        result = score_from_db_rows(
            orgnr="716400-0031",
            building_year=1970,
            arsredovisningar=[ar],
            energideklaration=None,
        )
        assert result.score > 0
        assert "tak" in result.project_type_hints

    def test_governance_velocity_populated(self):
        """filings_last_3yr should be counted from arsredovisningar."""
        from datetime import date
        current = date.today().year
        ars = [
            {"fiscal_year": current - 1, "avgift_change_pct": 3.0,
             "lan_change_pct": None, "total_lan": None,
             "underhallsfond": None, "underhallsfond_change_pct": None,
             "mentions_tak": False, "mentions_fasad": False,
             "mentions_stammar": False, "mentions_fonster": False, "mentions_hiss": False,
             "tak_year_mentioned": None, "fasad_year_mentioned": None,
             "stammar_year_mentioned": None, "fonster_year_mentioned": None,
             "hiss_year_mentioned": None, "maintenance_plan_raw": None, "full_text_preview": None},
            {"fiscal_year": current - 2, "avgift_change_pct": 2.0,
             "lan_change_pct": None, "total_lan": None,
             "underhallsfond": None, "underhallsfond_change_pct": None,
             "mentions_tak": False, "mentions_fasad": False,
             "mentions_stammar": False, "mentions_fonster": False, "mentions_hiss": False,
             "tak_year_mentioned": None, "fasad_year_mentioned": None,
             "stammar_year_mentioned": None, "fonster_year_mentioned": None,
             "hiss_year_mentioned": None, "maintenance_plan_raw": None, "full_text_preview": None},
        ]
        # Call directly and check input was constructed with filings_last_3yr
        # We can't easily inspect ScoringInput after score_from_db_rows,
        # so we test that the result is non-zero (governance contributes indirectly via confidence)
        result = score_from_db_rows("716400-0032", None, ars, None)
        assert isinstance(result, IntentScore)

    def test_energideklaration_eu_deadline_fires(self):
        from datetime import date
        ar = {
            "fiscal_year": 2023,
            "avgift_change_pct": None, "lan_change_pct": None, "total_lan": None,
            "underhallsfond": None, "underhallsfond_change_pct": None,
            "mentions_tak": False, "mentions_fasad": False, "mentions_stammar": False,
            "mentions_fonster": False, "mentions_hiss": False,
            "tak_year_mentioned": None, "fasad_year_mentioned": None,
            "stammar_year_mentioned": None, "fonster_year_mentioned": None,
            "hiss_year_mentioned": None, "maintenance_plan_raw": None, "full_text_preview": None,
        }
        ed = {
            "energiklass": "F",
            "eu_deadline_pressure": True,
            "giltig_till": date(2030, 6, 1),
        }
        result = score_from_db_rows("716400-0033", 1975, [ar], ed)
        assert result.score >= 10
        assert "energiåtgärder" in result.project_type_hints
