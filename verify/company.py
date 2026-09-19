"""
verify/company.py

swedish_company_verify_v1 — official-registry company verification.

One orgnr or company name in, one normalized and cited answer out:
canonical identity, legal status, registrations Norric tracks, insolvency
flags, latest recorded Bolagsverket changes, and per-source observation
timestamps with evidence links.

NO MOCK DATA. Fields Norric does not track (VAT/moms, employer registration)
return status "not_tracked". Missing optional sources degrade to null plus a
warning — never to a fabricated value. See docs/no-fabrication-contract.md.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

TOOL_NAME = "swedish_company_verify_v1"

_TIER_FROM_BAND = {1: "HEALTHY", 2: "WATCH", 3: "ELEVATED", 4: "HIGH", 5: "CRITICAL"}

_ENTITY_SQL = """
    SELECT orgnr, orgnr_display, name, orgform, is_active, deregistered_at,
           street, city, postcode, kommunkod, county, source,
           first_seen_at, last_seen_at, last_updated_at
    FROM norric_entities
    WHERE orgnr IN (:orgnr_digits, :orgnr_dashed)
"""

_NAME_SQL = """
    SELECT orgnr, name, is_active
    FROM norric_entities
    WHERE name ILIKE :pattern
    ORDER BY is_active DESC, name ASC
    LIMIT 5
"""

_PROFILE_SQL = """
    SELECT lifecycle_stage, f_skatt_active_at, f_skatt_revoked_at,
           ownership_changes_12m, ownership_last_change_at, kreditvakt_scored_at
    FROM company_profiles
    WHERE orgnr = :orgnr
"""

_KONKURS_SQL = """
    SELECT case_ref, filed_at, status_code, is_active, resolved_at
    FROM norric_payment_signals
    WHERE orgnr = :orgnr AND raw_data->>'signal_type' = 'konkurs'
    ORDER BY filed_at DESC NULLS LAST
    LIMIT 5
"""

_KRONOFOGDEN_SQL = """
    SELECT COUNT(*) FILTER (WHERE filed_at >= now()::date - 180) AS cases_last_6mo,
           MAX(filed_at)                                        AS latest_filed,
           SUM(claim_amount_sek) FILTER (WHERE is_active)       AS total_active_claim_sek
    FROM norric_payment_signals
    WHERE orgnr = :orgnr
      AND COALESCE(raw_data->>'signal_type', 'kronofogden') <> 'konkurs'
"""

_TAX_SQL = """
    SELECT amount_sek, last_seen_at
    FROM norric_tax_signals
    WHERE orgnr = :orgnr AND is_active = true
    ORDER BY last_seen_at DESC
    LIMIT 1
"""

_SCORE_SQL = """
    SELECT risk_band, distress_probability, scored_at, score_source
    FROM company_scores
    WHERE orgnr = :orgnr
"""

_CHANGES_SQL = """
    SELECT snapshot_date, field_name, old_value, new_value
    FROM norric_field_changes
    WHERE entity_id = :orgnr AND entity_type = 'company' AND source = 'bolagsverket'
    ORDER BY snapshot_date DESC
    LIMIT 5
"""

_PIPELINES_SQL = """
    SELECT pipeline,
           MAX(completed_at) FILTER (WHERE status = 'success') AS last_success,
           MAX(started_at)                                     AS last_attempt
    FROM norric_pipeline_runs
    GROUP BY pipeline
"""


def normalize_orgnr(value: str) -> str:
    """Normalize a Swedish orgnr to ######-#### form. Raises ValueError."""
    clean = value.replace("-", "").replace(" ", "")
    if not re.fullmatch(r"\d{10}", clean) or clean[0] == "0":
        raise ValueError(
            f"Invalid Swedish organisation number: {value!r}. Example: 556000-1234"
        )
    return f"{clean[:6]}-{clean[6:]}"


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _allabolag_url(orgnr: str) -> str:
    return f"https://www.allabolag.se/{orgnr.replace('-', '')}"


def _optional(db: Session, sql: str, params: dict, label: str, warnings: list[str]):
    """Run an enrichment query; on failure degrade to None with a warning."""
    try:
        return db.execute(text(sql), params)
    except Exception as exc:
        log.warning("[%s] optional source %s failed: %s: %s",
                    params.get("orgnr"), label, type(exc).__name__, exc)
        try:
            db.rollback()
        except Exception:
            pass
        warnings.append(f"{label}: source unavailable ({type(exc).__name__})")
        return None


def verify_company(db: Session, query: str) -> dict:
    """
    Verify a Swedish company from live registry tables. NEVER fabricates.

    Returns {data, sources, confidence, signals, warnings}.
    data.found=false when the orgnr/name is not in the registry mirror.
    data.match="ambiguous" with candidates when a name matches several companies.
    """
    warnings: list[str] = []
    signals: list[dict] = []
    query = (query or "").strip()
    if not query:
        raise ValueError("query must be an orgnr (556000-1234) or a company name")

    # ── Resolve orgnr ────────────────────────────────────────────────────────
    if re.fullmatch(r"[\d\- ]{10,13}", query):
        orgnr = normalize_orgnr(query)
        entity = db.execute(
            text(_ENTITY_SQL),
            {"orgnr_digits": orgnr.replace("-", ""), "orgnr_dashed": orgnr},
        ).fetchone()
    else:
        rows = _optional(db, _NAME_SQL, {"pattern": f"%{query}%"}, "name_search", warnings)
        candidates = list(rows) if rows else []
        if len(candidates) > 1:
            return {
                "data": {
                    "query": query,
                    "found": False,
                    "match": "ambiguous",
                    "verified": None,
                    "candidates": [
                        {"orgnr": normalize_orgnr(r.orgnr), "name": r.name,
                         "is_active": r.is_active}
                        for r in candidates
                    ],
                },
                "sources": ["bolagsverket"],
                "confidence": 0.3,
                "signals": [],
                "warnings": warnings
                + ["ambiguous name match — retry with the orgnr of the intended company"],
            }
        if len(candidates) == 1:
            raw = candidates[0].orgnr
            orgnr = normalize_orgnr(raw)
            entity = db.execute(
                text(_ENTITY_SQL),
                {"orgnr_digits": orgnr.replace("-", ""), "orgnr_dashed": orgnr},
            ).fetchone()
        else:
            entity = None
            orgnr = None

    if entity is None:
        data = {
            "query": query,
            "found": False,
            "match": "none",
            "verified": False,
        }
        if orgnr:
            data["orgnr"] = orgnr
        return {
            "data": data,
            "sources": ["bolagsverket"],
            "confidence": 0.3,
            "signals": [],
            "warnings": warnings
            + ["not found in the Bolagsverket registry mirror — "
               "the orgnr may be wrong or the entity outside current coverage"],
        }

    # Table formats differ by pipeline: entities/snapshots store digits only,
    # signal/score tables store dashed form. Carry both.
    orgnr_digits = entity.orgnr.replace("-", "")
    orgnr = entity.orgnr_display or normalize_orgnr(orgnr_digits)
    now = datetime.now(timezone.utc)

    # ── Identity + legal status ──────────────────────────────────────────────
    last_seen = entity.last_seen_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age_hours = (now - last_seen).total_seconds() / 3600 if last_seen else None
    if age_hours is None:
        confidence = 0.5
    elif age_hours <= 72:
        confidence = 0.95
    elif age_hours <= 35 * 24:
        confidence = 0.8
    else:
        confidence = 0.5
        warnings.append(f"registry mirror stale: last confirmed {age_hours / 24:.0f} days ago")

    identity = {
        "orgnr": orgnr,
        "orgnr_digits": orgnr_digits,
        "name": entity.name,
        "orgform": entity.orgform,
        "registered_address": {
            "street": entity.street,
            "postcode": entity.postcode,
            "city": entity.city,
            "kommunkod": entity.kommunkod,
            "county": entity.county,
        },
        "registry_source": entity.source,
        "registry_first_seen_at": _iso(entity.first_seen_at),
        "registry_last_confirmed_at": _iso(entity.last_seen_at),
    }
    legal_status = {
        "is_active": entity.is_active,
        "status": "active" if entity.is_active else "deregistered",
        "deregistered_at": _iso(entity.deregistered_at),
    }

    # ── Registrations ────────────────────────────────────────────────────────
    f_tax = {"status": "unknown", "active_since": None, "revoked_at": None}
    profile_row = _optional(db, _PROFILE_SQL, {"orgnr": orgnr}, "company_profiles", warnings)
    profile = profile_row.fetchone() if profile_row is not None else None
    if profile is not None:
        if profile.f_skatt_revoked_at:
            f_tax = {"status": "revoked",
                     "active_since": _iso(profile.f_skatt_active_at),
                     "revoked_at": _iso(profile.f_skatt_revoked_at)}
        elif profile.f_skatt_active_at:
            f_tax = {"status": "active",
                     "active_since": _iso(profile.f_skatt_active_at),
                     "revoked_at": None}
    registrations = {
        "f_tax": f_tax,
        "vat": {"status": "not_tracked"},
        "employer": {"status": "not_tracked"},
    }

    # ── Insolvency flags ─────────────────────────────────────────────────────
    konkurs_rows_r = _optional(db, _KONKURS_SQL, {"orgnr": orgnr}, "konkurs", warnings)
    konkurs_rows = list(konkurs_rows_r) if konkurs_rows_r is not None else []
    in_konkurs = any(r.is_active and not r.resolved_at for r in konkurs_rows)
    latest_filing = None
    if konkurs_rows:
        r = konkurs_rows[0]
        latest_filing = {
            "filed_at": _iso(r.filed_at),
            "status_code": r.status_code,
            "case_ref": r.case_ref,
            "is_active": r.is_active,
        }

    kron_r = _optional(db, _KRONOFOGDEN_SQL, {"orgnr": orgnr}, "kronofogden", warnings)
    kron = kron_r.fetchone() if kron_r is not None else None
    kronofogden_cases_6m = int(kron.cases_last_6mo or 0) if kron else None

    tax_r = _optional(db, _TAX_SQL, {"orgnr": orgnr}, "skatteverket", warnings)
    tax = tax_r.fetchone() if tax_r is not None else None

    insolvency = {
        "in_konkurs": in_konkurs,
        "konkurs_filings_tracked": len(konkurs_rows),
        "latest_konkurs_filing": latest_filing,
        "kronofogden_cases_6m": kronofogden_cases_6m,
        "kronofogden_latest_filed": _iso(kron.latest_filed) if kron else None,
        "kronofogden_active_claim_sek": int(kron.total_active_claim_sek)
        if kron and kron.total_active_claim_sek else 0,
        "tax_debt_listed": tax is not None,
        "tax_debt_amount_sek": int(tax.amount_sek) if tax and tax.amount_sek else None,
        "tax_debt_last_seen_at": _iso(tax.last_seen_at) if tax else None,
    }
    if in_konkurs:
        signals.append({"key": "in_konkurs", "label": "Aktivt konkursärende",
                        "value": True, "source": "bolagsverket", "direction": "risk"})
    if tax is not None:
        signals.append({"key": "skatteverket_flag", "label": "På restanslängden",
                        "value": int(tax.amount_sek or 0), "source": "skatteverket",
                        "direction": "risk"})
    if kronofogden_cases_6m:
        signals.append({"key": "kronofogden_count",
                        "label": f"Betalningsförelägganden: {kronofogden_cases_6m} senaste 6 mån",
                        "value": kronofogden_cases_6m, "source": "kronofogden",
                        "direction": "risk"})

    # ── Cached risk score (read-only — never recomputed here) ────────────────
    score_r = _optional(db, _SCORE_SQL, {"orgnr": orgnr}, "company_scores", warnings)
    score = score_r.fetchone() if score_r is not None else None
    risk = None
    if score is not None and score.score_source == "live":
        risk = {
            "risk_band": score.risk_band,
            "risk_tier": _TIER_FROM_BAND.get(score.risk_band),
            "distress_probability": score.distress_probability,
            "scored_at": _iso(score.scored_at),
            "detail_tool": "kreditvakt_score_company_v1",
        }

    # ── Latest recorded registry changes ─────────────────────────────────────
    changes_r = _optional(db, _CHANGES_SQL, {"orgnr": orgnr_digits}, "registry_changes", warnings)
    latest_changes = [
        {"snapshot_date": _iso(r.snapshot_date), "field": r.field_name,
         "from": r.old_value, "to": r.new_value}
        for r in changes_r
    ] if changes_r is not None else []

    # ── Source freshness ─────────────────────────────────────────────────────
    pipes_r = _optional(db, _PIPELINES_SQL, {}, "pipeline_runs", warnings)
    sources_freshness = {
        r.pipeline: {"last_success": _iso(r.last_success),
                     "last_attempt": _iso(r.last_attempt)}
        for r in pipes_r
    } if pipes_r is not None else {}

    verified = bool(entity.is_active)

    data = {
        "query": query,
        "found": True,
        "match": "exact",
        "verified": verified,
        "identity": identity,
        "legal_status": legal_status,
        "registrations": registrations,
        "insolvency": insolvency,
        "risk": risk,
        "latest_changes": latest_changes,
        "sources": sources_freshness,
        "evidence": {
            "basis": "Norric mirror of Bolagsverket bulk registry plus tracked signal pipelines",
            "registry_last_confirmed_at": _iso(entity.last_seen_at),
            "reference_links": {
                "bolagsverket_foretagsinfo": "https://foretagsinfo.bolagsverket.se/sok-foretagsinformation-web/",
                "allabolag": _allabolag_url(orgnr),
            },
        },
    }
    return {
        "data": data,
        "sources": ["bolagsverket", "skatteverket", "kronofogden"],
        "confidence": confidence,
        "signals": signals,
        "warnings": warnings,
    }
