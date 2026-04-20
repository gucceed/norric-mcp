"""
tests/test_provenance.py

100% coverage on core/provenance.py
Run with: pytest tests/test_provenance.py -v --tb=short
"""

import pytest
from datetime import datetime, timezone, timedelta

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.provenance import (
    Agency,
    NorricProvenance,
    ConfidenceTier,
    confidence_tier,
    min_confidence,
    make_document_ref,
    make_kommun_source_id,
    bolagsverket_provenance,
    kronofogden_provenance,
    boverket_provenance,
    signal_provenance,
)


# ---------------------------------------------------------------------------
# Agency enum
# ---------------------------------------------------------------------------

class TestAgency:
    def test_all_agencies_have_display_names(self):
        for agency in Agency:
            assert agency.display_name, f"{agency} missing display name"

    def test_all_agencies_have_domains(self):
        for agency in Agency:
            assert len(agency.data_domains) > 0, f"{agency} missing domains"

    def test_bolagsverket_domains(self):
        assert "company_registration" in Agency.BOLAGSVERKET.data_domains

    def test_kronofogden_domains(self):
        assert "restanslangd" in Agency.KRONOFOGDEN.data_domains


# ---------------------------------------------------------------------------
# make_kommun_source_id
# ---------------------------------------------------------------------------

class TestMakeKommunSourceId:
    def test_valid_kommunkod(self):
        assert make_kommun_source_id("1280") == "kommun:1280"

    def test_valid_kommunkod_stockholm(self):
        assert make_kommun_source_id("0180") == "kommun:0180"

    def test_invalid_non_digits(self):
        with pytest.raises(ValueError, match="4 digits"):
            make_kommun_source_id("ABCD")

    def test_invalid_too_short(self):
        with pytest.raises(ValueError):
            make_kommun_source_id("128")

    def test_invalid_too_long(self):
        with pytest.raises(ValueError):
            make_kommun_source_id("12800")


# ---------------------------------------------------------------------------
# make_document_ref
# ---------------------------------------------------------------------------

class TestMakeDocumentRef:
    def test_with_period(self):
        ref = make_document_ref(Agency.BOLAGSVERKET, "5565123456", "arsredovisning", "2024")
        assert ref == "bolagsverket:5565123456/arsredovisning/2024"

    def test_without_period(self):
        ref = make_document_ref(Agency.KRONOFOGDEN, "5565123456", "restanslangd")
        assert ref == "kronofogden:5565123456/restanslangd"

    def test_string_agency(self):
        ref = make_document_ref("bolagsverket", "9999999999", "arsredovisning", "2023")
        assert ref == "bolagsverket:9999999999/arsredovisning/2023"

    def test_municipality_agency_string(self):
        ref = make_document_ref("kommun:1280", "2024-12345", "procurement_notice")
        assert ref == "kommun:1280:2024-12345/procurement_notice"


# ---------------------------------------------------------------------------
# confidence_tier
# ---------------------------------------------------------------------------

class TestConfidenceTier:
    def test_direct(self):
        assert confidence_tier(1.0) == ConfidenceTier.DIRECT

    def test_parsed_high(self):
        assert confidence_tier(0.99) == ConfidenceTier.PARSED

    def test_parsed_low(self):
        assert confidence_tier(0.8) == ConfidenceTier.PARSED

    def test_inferred_high(self):
        assert confidence_tier(0.79) == ConfidenceTier.INFERRED

    def test_inferred_low(self):
        assert confidence_tier(0.5) == ConfidenceTier.INFERRED

    def test_estimated_high(self):
        assert confidence_tier(0.49) == ConfidenceTier.ESTIMATED

    def test_estimated_zero(self):
        assert confidence_tier(0.0) == ConfidenceTier.ESTIMATED


# ---------------------------------------------------------------------------
# min_confidence
# ---------------------------------------------------------------------------

class TestMinConfidence:
    def _make_prov(self, confidence: float) -> NorricProvenance:
        return NorricProvenance(
            source_agency=Agency.BOLAGSVERKET.value,
            source_document_ref="bolagsverket:5565123456/arsredovisning/2024",
            confidence=confidence,
        )

    def test_single_record(self):
        assert min_confidence([self._make_prov(0.9)]) == 0.9

    def test_multiple_records_returns_min(self):
        records = [self._make_prov(0.9), self._make_prov(0.6), self._make_prov(1.0)]
        assert min_confidence(records) == 0.6

    def test_empty_returns_zero(self):
        assert min_confidence([]) == 0.0


# ---------------------------------------------------------------------------
# NorricProvenance model
# ---------------------------------------------------------------------------

class TestNorricProvenance:
    def _valid(self, **kwargs) -> NorricProvenance:
        defaults = dict(
            source_agency=Agency.BOLAGSVERKET.value,
            source_document_ref="bolagsverket:5565123456/arsredovisning/2024",
            confidence=0.9,
        )
        defaults.update(kwargs)
        return NorricProvenance(**defaults)

    # -- Construction
    def test_minimal_construction(self):
        p = self._valid()
        assert p.source_agency == "bolagsverket"
        assert p.schema_version == "1.0"
        assert p.raw_url is None
        assert p.ingested_at.tzinfo == timezone.utc

    def test_all_known_agencies_accepted(self):
        for agency in Agency:
            p = self._valid(source_agency=agency.value)
            assert p.source_agency == agency.value

    def test_municipality_agency_accepted(self):
        p = self._valid(source_agency="kommun:1280")
        assert p.source_agency == "kommun:1280"

    def test_unknown_agency_rejected(self):
        with pytest.raises(ValueError, match="Unknown source_agency"):
            self._valid(source_agency="finansen")

    def test_invalid_municipality_format_rejected(self):
        with pytest.raises(ValueError, match="4-digit-kommunkod"):
            self._valid(source_agency="kommun:128")

    def test_confidence_bounds_upper(self):
        p = self._valid(confidence=1.0)
        assert p.confidence == 1.0

    def test_confidence_bounds_lower(self):
        p = self._valid(confidence=0.0)
        assert p.confidence == 0.0

    def test_confidence_over_1_rejected(self):
        with pytest.raises(Exception):
            self._valid(confidence=1.01)

    def test_confidence_under_0_rejected(self):
        with pytest.raises(Exception):
            self._valid(confidence=-0.01)

    def test_naive_datetime_gets_utc(self):
        naive = datetime(2026, 4, 20, 12, 0, 0)
        p = self._valid(ingested_at=naive)
        assert p.ingested_at.tzinfo == timezone.utc

    def test_immutable(self):
        p = self._valid()
        with pytest.raises(Exception):
            p.confidence = 0.5  # frozen model

    # -- Properties
    def test_tier_property(self):
        p = self._valid(confidence=1.0)
        assert p.tier == ConfidenceTier.DIRECT

    def test_agency_display_name_known(self):
        p = self._valid(source_agency=Agency.BOLAGSVERKET.value)
        assert "Bolagsverket" in p.agency_display_name

    def test_agency_display_name_municipality(self):
        p = self._valid(source_agency="kommun:1280")
        assert "1280" in p.agency_display_name

    def test_agency_display_name_unknown_fallback(self):
        # Bypass validator to test unknown agency fallback in display_name
        p = NorricProvenance.model_construct(
            source_agency="xyzunknown",
            source_document_ref="xyzunknown:123/test",
            confidence=0.5,
            ingested_at=datetime.now(timezone.utc),
            schema_version="1.0",
            raw_url=None,
        )
        assert p.agency_display_name == "xyzunknown"

    # -- is_stale
    def test_fresh_record_not_stale(self):
        p = self._valid()
        assert p.is_stale(max_age_days=7) is False

    def test_old_record_is_stale(self):
        old = datetime.now(timezone.utc) - timedelta(days=10)
        p = self._valid(ingested_at=old)
        assert p.is_stale(max_age_days=7) is True

    def test_exactly_threshold_not_stale(self):
        threshold = datetime.now(timezone.utc) - timedelta(days=7)
        p = self._valid(ingested_at=threshold)
        # age.days == 7, threshold is >7, so not stale
        assert p.is_stale(max_age_days=7) is False

    # -- to_compliance_dict
    def test_compliance_dict_structure(self):
        p = self._valid(confidence=1.0)
        d = p.to_compliance_dict()
        assert "agency" in d
        assert "document_ref" in d
        assert "ingested_at_utc" in d
        assert "confidence_score" in d
        assert "confidence_tier" in d
        assert "is_stale" in d
        assert d["eu_ai_act_ready"] if "eu_ai_act_ready" in d else True  # optional

    def test_compliance_dict_confidence_tier_string(self):
        p = self._valid(confidence=1.0)
        d = p.to_compliance_dict()
        assert d["confidence_tier"] == "direct"

    def test_compliance_dict_ingested_at_is_iso(self):
        p = self._valid()
        d = p.to_compliance_dict()
        # Should parse as ISO datetime without error
        datetime.fromisoformat(d["ingested_at_utc"])


# ---------------------------------------------------------------------------
# Convenience builders
# ---------------------------------------------------------------------------

class TestConvenienceBuilders:
    def test_bolagsverket_provenance(self):
        p = bolagsverket_provenance("5565123456", "arsredovisning", "2024")
        assert p.source_agency == "bolagsverket"
        assert "5565123456" in p.source_document_ref
        assert "arsredovisning" in p.source_document_ref
        assert "2024" in p.source_document_ref

    def test_bolagsverket_provenance_no_period(self):
        p = bolagsverket_provenance("5565123456", "konkurs")
        assert p.source_agency == "bolagsverket"

    def test_kronofogden_provenance(self):
        p = kronofogden_provenance("5565123456")
        assert p.source_agency == "kronofogden"
        assert p.confidence == 1.0  # direct extraction

    def test_boverket_provenance(self):
        p = boverket_provenance("BLD-12345")
        assert p.source_agency == "boverket"
        assert "energideklaration" in p.source_document_ref

    def test_signal_provenance(self):
        p = signal_provenance("1280", "2024-NOTICE-001")
        assert p.source_agency == "kommun:1280"
        assert "procurement_notice" in p.source_document_ref

    def test_signal_provenance_invalid_kommunkod(self):
        with pytest.raises(ValueError):
            signal_provenance("999", "notice-1")

    def test_builders_return_immutable_records(self):
        p = bolagsverket_provenance("5565123456", "arsredovisning")
        with pytest.raises(Exception):
            p.confidence = 0.5


# ---------------------------------------------------------------------------
# Envelope integration
# ---------------------------------------------------------------------------

class TestEnvelopeIntegration:
    """Tests that NorricResponse correctly integrates provenance."""

    def test_response_derives_confidence_from_provenance(self):
        from core.envelope import NorricResponse
        provenance = [
            bolagsverket_provenance("5565123456", "arsredovisning", confidence=0.9),
            kronofogden_provenance("5565123456", confidence=0.7),
        ]
        resp = NorricResponse.ok(
            tool="kreditvakt_score_company_v1",
            data={"insolvency_score": 72},
            provenance=provenance,
        )
        # Weakest-link: min(0.9, 0.7) = 0.7
        assert resp.confidence == pytest.approx(0.7)

    def test_response_without_provenance_keeps_tool_confidence(self):
        from core.envelope import NorricResponse
        resp = NorricResponse.ok(
            tool="kreditvakt_score_company_v1",
            data={"insolvency_score": 72},
            confidence=0.85,
        )
        assert resp.confidence == pytest.approx(0.85)

    def test_has_provenance_true(self):
        from core.envelope import NorricResponse
        resp = NorricResponse.ok(
            tool="test",
            data={},
            provenance=[bolagsverket_provenance("5565123456", "arsredovisning")],
        )
        assert resp.has_provenance is True

    def test_has_provenance_false(self):
        from core.envelope import NorricResponse
        resp = NorricResponse.ok(tool="test", data={})
        assert resp.has_provenance is False

    def test_provenance_summary_structure(self):
        from core.envelope import NorricResponse
        old = datetime.now(timezone.utc) - timedelta(days=10)
        resp = NorricResponse.ok(
            tool="test",
            data={},
            provenance=[
                bolagsverket_provenance("5565123456", "arsredovisning", confidence=0.9),
                NorricProvenance(
                    source_agency="kronofogden",
                    source_document_ref="kronofogden:5565123456/restanslangd",
                    confidence=0.6,
                    ingested_at=old,
                ),
            ],
        )
        summary = resp.provenance_summary()
        assert summary is not None
        assert summary["record_count"] == 2
        assert "bolagsverket" in summary["agencies"]
        assert summary["any_stale"] is True
        assert summary["min_confidence"] == pytest.approx(0.6)

    def test_provenance_summary_none_when_no_provenance(self):
        from core.envelope import NorricResponse
        resp = NorricResponse.ok(tool="test", data={})
        assert resp.provenance_summary() is None

    def test_is_stale_true_when_stale_record(self):
        from core.envelope import NorricResponse
        old = datetime.now(timezone.utc) - timedelta(days=10)
        resp = NorricResponse.ok(
            tool="test",
            data={},
            provenance=[
                NorricProvenance(
                    source_agency="bolagsverket",
                    source_document_ref="bolagsverket:5565123456/arsredovisning/2024",
                    confidence=0.9,
                    ingested_at=old,
                )
            ],
        )
        assert resp.is_stale is True

    def test_err_response(self):
        from core.envelope import NorricResponse
        resp = NorricResponse.err(
            tool="kreditvakt_score_company_v1",
            error="Bolagsverket rate limit exceeded",
        )
        assert resp.success is False
        assert resp.confidence == 0.0
        assert resp.error == "Bolagsverket rate limit exceeded"
