"""
Unit tests for ingestion.bolagsverket.konkurs_parser.

Coverage:
  - Org-form filter: AB / BRF retained, others (HB, S) excluded by default.
  - KK-AVOMFO row → emitted with status_code "KK-AVOMFO", is_active=True,
    KONKURS_FILED category.
  - FR-AVOMFO row → no konkurs record emitted (FR is EARLY_WARNING, not konkurs).
  - KK-AVOMFO + KKAVOV-AVSLAVOMFO pair → single record, status_code updated to
    KKAVOV-AVSLAVOMFO, is_active=False, resolved_at populated.
  - KKAV-AVORG in field 6 (deregistration reason) → synthetic record with
    status_code "KKAV-AVORG", is_active=False.
  - 24-month cutoff: KK-AVOMFO from 25 months ago is dropped.
  - documentation_status tag: documented codes → "documented",
    suffix-variant codes → "empirical".
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ingestion.bolagsverket.konkurs_parser import (
    ACTIVE_PROCEEDING_CODES,
    ALPHABETIC_TO_NUMERIC_MAPPING,
    DEFAULT_ORG_FORMS,
    DEREG_REASON_CODES,
    KONKURS_SIGNAL_CATEGORIES,
    RESOLVED_PROCEEDING_CODES,
    _documentation_status,
    _extract_orgnr,
    _extract_primary_name,
    _parse_field7_events,
    parse_konkurs_events,
)


# ── helpers ───────────────────────────────────────────────────────────────────

HEADER = (
    "organisationsidentitet;namnskyddslopnummer;registreringsland;"
    "organisationsnamn;organisationsform;avregistreringsdatum;"
    "avregistreringsorsak;pagandeAvvecklingsEllerOmstruktureringsforfarande;"
    "registreringsdatum;verksamhetsbeskrivning;postadress"
)


def _row(
    orgnr: str = "5560000010",
    seq: str = "1",
    name: str = "Acme AB",
    orgform: str = "AB-ORGFO",
    dereg_date: str = "",
    dereg_reason: str = "",
    field7: str = "",
    reg_date: str = "2020-01-01",
    verksamhet: str = "Test verksamhet",
    address: str = "Storgatan 1$$Stockholm$11122$SE-LAND",
) -> str:
    return ";".join(
        f'"{v}"' for v in (
            f"{orgnr}$ORGNR-IDORG",
            seq,
            "SE-LAND",
            f"{name}$FORETAGSNAMN-ORGNAM${reg_date}",
            orgform,
            dereg_date,
            dereg_reason,
            field7,
            reg_date,
            verksamhet,
            address,
        )
    )


def _write_sample(tmp_path: Path, rows: list[str]) -> Path:
    p = tmp_path / "sample_bulkfil.txt"
    p.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return p


def _today_relative(months: int) -> date:
    today = date.today()
    y, m = today.year, today.month + months
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, min(today.day, 28))


# ── pure-helper tests ─────────────────────────────────────────────────────────


def test_extract_orgnr_normalises_dash_format():
    assert _extract_orgnr("556000-0010$ORGNR-IDORG") == "5560000010"


def test_extract_orgnr_returns_none_on_short():
    assert _extract_orgnr("12345$ORGNR-IDORG") is None


def test_extract_primary_name_strips_type_tag_and_date():
    raw = "BRF Källan 1$FORETAGSNAMN-ORGNAM$2015-05-08"
    assert _extract_primary_name(raw) == "BRF Källan 1"


def test_extract_primary_name_takes_first_when_multiple():
    raw = "Primary AB$FORETAGSNAMN-ORGNAM$2010-01-01|Alt$SARS_FORNAMN-ORGNAM$2015-01-01$scope"
    assert _extract_primary_name(raw) == "Primary AB"


def test_parse_field7_events_returns_sorted():
    raw = "|KKAVOV-AVSLAVOMFO$2025-03-11|KK-AVOMFO$2024-06-05"
    events = _parse_field7_events(raw)
    assert events == [
        ("KK-AVOMFO", date(2024, 6, 5)),
        ("KKAVOV-AVSLAVOMFO", date(2025, 3, 11)),
    ]


def test_parse_field7_events_skips_malformed_and_empty():
    assert _parse_field7_events("") == []
    assert _parse_field7_events("|MALFORMED-NO-DOLLAR") == []
    assert _parse_field7_events("|GOODCODE$not-a-date") == []


# ── documentation_status tag ──────────────────────────────────────────────────


def test_documentation_status_documented_for_kodlista_codes():
    assert _documentation_status("KK-AVOMFO") == "documented"
    assert _documentation_status("KKAV-AVORG") == "documented"
    assert _documentation_status("FR-AVOMFO") == "documented"


def test_documentation_status_empirical_for_suffix_variants():
    assert _documentation_status("KKAVOV-AVSLAVOMFO") == "empirical"
    assert _documentation_status("KKUHAVD-AVSLAVOMFO") == "empirical"
    assert _documentation_status("FRUHOR-AVSLAVOMFO") == "empirical"


def test_documentation_status_unknown_for_truly_unknown_codes():
    assert _documentation_status("FUTURE-NEW-CODE-XYZ") == "unknown"


# ── signal category integrity ─────────────────────────────────────────────────


def test_konkurs_filed_category_contains_kk_initiation_and_concluded():
    cat = KONKURS_SIGNAL_CATEGORIES["KONKURS_FILED"]
    assert "KK-AVOMFO" in cat
    assert "KKAV-AVORG" in cat


def test_signal_categories_are_disjoint():
    seen = set()
    for cat_name, codes in KONKURS_SIGNAL_CATEGORIES.items():
        for code in codes:
            assert code not in seen, (
                f"code {code} appears in {cat_name} and another category"
            )
            seen.add(code)


def test_alphabetic_to_numeric_mapping_covers_konkurs_lifecycle():
    # Every code in KONKURS_FILED + KONKURS_REVERSED must have a numeric bridge
    for code in (KONKURS_SIGNAL_CATEGORIES["KONKURS_FILED"]
                 | KONKURS_SIGNAL_CATEGORIES["KONKURS_REVERSED"]):
        assert code in ALPHABETIC_TO_NUMERIC_MAPPING, f"missing numeric for {code}"


# ── parse_konkurs_events integration tests ────────────────────────────────────


def test_orgform_filter_excludes_non_default_forms(tmp_path: Path):
    recent = _today_relative(-3).isoformat()
    rows = [
        _row(orgnr="5560000010", orgform="AB-ORGFO",
             field7=f"|KK-AVOMFO${recent}"),
        _row(orgnr="7690000020", orgform="BRF-ORGFO",
             field7=f"|KK-AVOMFO${recent}"),
        _row(orgnr="9690000030", orgform="HB-ORGFO",
             field7=f"|KK-AVOMFO${recent}"),  # should be excluded
        _row(orgnr="8020000040", orgform="S-ORGFO",
             field7=f"|KK-AVOMFO${recent}"),  # should be excluded
    ]
    path = _write_sample(tmp_path, rows)
    out = list(parse_konkurs_events(path))
    orgnrs = {r["orgnr"] for r in out}
    assert orgnrs == {"556000-0010", "769000-0020"}


def test_kk_avomfo_only_emits_active_konkurs(tmp_path: Path):
    filed_at = _today_relative(-3)
    rows = [_row(field7=f"|KK-AVOMFO${filed_at.isoformat()}")]
    out = list(parse_konkurs_events(_write_sample(tmp_path, rows)))
    assert len(out) == 1
    rec = out[0]
    assert rec["status_code"] == "KK-AVOMFO"
    assert rec["filed_at"] == filed_at
    assert rec["is_active"] is True
    assert rec["resolved_at"] is None
    assert rec["raw_data"]["signal_type"] == "konkurs"
    assert rec["raw_data"]["status_numeric"] == "20"
    assert rec["raw_data"]["documentation_status"] == "documented"
    assert rec["orgnr"] == "556000-0010"  # dashed format per scorer convention
    assert rec["case_ref"] == f"bv-konkurs-5560000010-{filed_at.isoformat()}"  # internal id stays no-dash


def test_kk_avomfo_with_resolution_yields_resolved_record(tmp_path: Path):
    filed_at = _today_relative(-12)
    resolved_at = _today_relative(-2)
    field7 = (
        f"|KK-AVOMFO${filed_at.isoformat()}"
        f"|KKAVOV-AVSLAVOMFO${resolved_at.isoformat()}"
    )
    rows = [_row(field7=field7)]
    out = list(parse_konkurs_events(_write_sample(tmp_path, rows)))
    assert len(out) == 1
    rec = out[0]
    assert rec["status_code"] == "KKAVOV-AVSLAVOMFO"
    assert rec["filed_at"] == filed_at  # case_ref stable on initiation date
    assert rec["resolved_at"] == resolved_at
    assert rec["is_active"] is False
    assert rec["raw_data"]["documentation_status"] == "empirical"
    assert rec["raw_data"]["status_numeric"] == "22"


def test_kkav_avorg_in_field6_emits_synthetic_record(tmp_path: Path):
    dereg_date = _today_relative(-6).isoformat()
    rows = [_row(
        dereg_date=dereg_date,
        dereg_reason="KKAV-AVORG",
        field7="",  # no field-7 KK event
    )]
    out = list(parse_konkurs_events(_write_sample(tmp_path, rows)))
    assert len(out) == 1
    rec = out[0]
    assert rec["status_code"] == "KKAV-AVORG"
    assert rec["is_active"] is False
    assert rec["raw_data"]["status_numeric"] == "21"


def test_kkav_avorg_skipped_when_field7_event_already_emitted(tmp_path: Path):
    """
    A company with both a field-7 KK-AVOMFO event AND a field-6 KKAV-AVORG
    deregistration reason should produce ONE record (from field 7), not two.
    Avoids double-counting the same filing.
    """
    filed_at = _today_relative(-12)
    dereg_date = _today_relative(-1).isoformat()
    rows = [_row(
        dereg_date=dereg_date,
        dereg_reason="KKAV-AVORG",
        field7=f"|KK-AVOMFO${filed_at.isoformat()}",
    )]
    out = list(parse_konkurs_events(_write_sample(tmp_path, rows)))
    assert len(out) == 1
    assert out[0]["filed_at"] == filed_at  # field-7 date wins


def test_24_month_cutoff_drops_old_events(tmp_path: Path):
    old = _today_relative(-30).isoformat()
    recent = _today_relative(-6).isoformat()
    rows = [
        _row(orgnr="5560000010", field7=f"|KK-AVOMFO${old}"),     # dropped
        _row(orgnr="5560000020", field7=f"|KK-AVOMFO${recent}"),  # kept
    ]
    out = list(parse_konkurs_events(_write_sample(tmp_path, rows)))
    orgnrs = {r["orgnr"] for r in out}
    assert orgnrs == {"556000-0020"}


def test_idempotency_same_input_yields_identical_output(tmp_path: Path):
    filed_at = _today_relative(-3).isoformat()
    rows = [_row(field7=f"|KK-AVOMFO${filed_at}")]
    path = _write_sample(tmp_path, rows)
    out1 = list(parse_konkurs_events(path))
    out2 = list(parse_konkurs_events(path))
    assert out1 == out2


def test_non_konkurs_field7_codes_do_not_emit_records(tmp_path: Path):
    recent = _today_relative(-3).isoformat()
    rows = [
        # FR-AVOMFO is EARLY_WARNING, not konkurs — should NOT emit konkurs record
        _row(orgnr="5560000010", field7=f"|FR-AVOMFO${recent}"),
        # LI-AVOMFO (voluntary liquidation) — should NOT emit konkurs record
        _row(orgnr="5560000020", field7=f"|LI-AVOMFO${recent}"),
    ]
    out = list(parse_konkurs_events(_write_sample(tmp_path, rows)))
    assert out == []
