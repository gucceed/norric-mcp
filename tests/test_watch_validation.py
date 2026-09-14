"""
tests/test_watch_validation.py

Event types, filters, tier limits and callback-URL SSRF guard.
Run with: pytest tests/test_watch_validation.py -v --tb=short
"""

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watch.validation import (
    DEFAULT_MIN_SCORE_DELTA,
    EVENT_TYPES_V1,
    entity_count,
    normalize_orgnr,
    tier_allows_watch,
    tier_entity_limit,
    validate_callback_url,
    validate_event_types,
    validate_filters,
)


class TestEventTypes:
    def test_all_v1_accepted(self):
        out = validate_event_types(sorted(EVENT_TYPES_V1))
        assert set(out) == EVENT_TYPES_V1

    def test_deduped_preserving_order(self):
        out = validate_event_types(["company.score_changed", "company.score_changed"])
        assert out == ["company.score_changed"]

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            validate_event_types([])

    def test_unknown_rejected_with_valid_list(self):
        with pytest.raises(ValueError, match="unknown event type"):
            validate_event_types(["company.vibes_changed"])

    def test_blocked_type_names_blocker(self):
        with pytest.raises(ValueError, match="not available"):
            validate_event_types(["municipality.tender_posted"])
        with pytest.raises(ValueError, match="not live"):
            validate_event_types(["company.annual_report_filed"])

    def test_phase2_type_rejected_for_now(self):
        with pytest.raises(ValueError, match="Phase 2"):
            validate_event_types(["brf.score_changed"])

    def test_non_string_rejected(self):
        with pytest.raises(ValueError):
            validate_event_types([123])


class TestOrgnr:
    def test_dashless_passthrough(self):
        assert normalize_orgnr("5560123456") == "5560123456"

    def test_dash_and_space_stripped(self):
        assert normalize_orgnr("556012-3456") == "5560123456"
        assert normalize_orgnr("556012 3456") == "5560123456"

    def test_invalid_rejected(self):
        for bad in ["123", "556012345", "abcdefghij", "0560123456"]:
            with pytest.raises(ValueError):
                normalize_orgnr(bad)


class TestFilters:
    def test_defaults(self):
        f = validate_filters(None)
        assert f == {"orgnrs": [], "min_score_delta": DEFAULT_MIN_SCORE_DELTA}

    def test_orgnrs_normalised_and_deduped(self):
        f = validate_filters({"orgnrs": ["556012-3456", "5560123456", "559123 4567"]})
        assert f["orgnrs"] == ["5560123456", "5591234567"]

    def test_unknown_keys_rejected(self):
        with pytest.raises(ValueError, match="unknown filter keys"):
            validate_filters({"orgnr": ["5560123456"]})  # singular typo

    def test_delta_bounds(self):
        assert validate_filters({"min_score_delta": 1})["min_score_delta"] == 1
        assert validate_filters({"min_score_delta": 20})["min_score_delta"] == 20
        for bad in [0, 21, -1, "3", 3.5, True]:
            with pytest.raises(ValueError):
                validate_filters({"min_score_delta": bad})

    def test_entity_count(self):
        assert entity_count({"orgnrs": ["5560123456", "5591234567"]}) == 2
        assert entity_count({}) == 0


class TestTierPolicy:
    def test_free_cannot_watch(self):
        assert not tier_allows_watch("free")
        assert tier_entity_limit("free") == 0

    def test_paid_tiers(self):
        assert tier_allows_watch("standard") and tier_entity_limit("standard") == 500
        assert tier_allows_watch("compliance") and tier_entity_limit("compliance") == 10_000

    def test_internal_tiers(self):
        assert tier_allows_watch("internal")
        assert tier_allows_watch("all")


class TestCallbackUrl:
    def test_valid_https(self):
        url = "https://platform.example.com/norric/webhook"
        assert validate_callback_url(url) == url

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="https"):
            validate_callback_url("http://platform.example.com/hook")

    def test_credentials_rejected(self):
        with pytest.raises(ValueError, match="credentials"):
            validate_callback_url("https://user:pass@example.com/hook")

    def test_fragment_rejected(self):
        with pytest.raises(ValueError, match="fragment"):
            validate_callback_url("https://example.com/hook#frag")

    def test_private_ip_literals_rejected(self):
        for url in [
            "https://127.0.0.1/hook",
            "https://10.0.0.5/hook",
            "https://192.168.1.10/hook",
            "https://172.16.0.1/hook",
            "https://169.254.169.254/latest/meta-data",  # cloud metadata
            "https://[::1]/hook",
            "https://0.0.0.0/hook",
        ]:
            with pytest.raises(ValueError, match="private or reserved"):
                validate_callback_url(url)

    def test_public_ip_literal_allowed(self):
        url = "https://8.8.8.8/hook"
        assert validate_callback_url(url) == url

    def test_doc_range_literal_rejected(self):
        # TEST-NET ranges are not globally reachable — treated as private
        with pytest.raises(ValueError, match="private or reserved"):
            validate_callback_url("https://203.0.113.10/hook")

    def test_internal_hostnames_rejected(self):
        for host in ["localhost", "foo.localhost", "db.internal", "nas.local"]:
            with pytest.raises(ValueError, match="not allowed"):
                validate_callback_url(f"https://{host}/hook")

    def test_empty_and_missing_host_rejected(self):
        for bad in ["", "https://", "https:///path"]:
            with pytest.raises(ValueError):
                validate_callback_url(bad)
