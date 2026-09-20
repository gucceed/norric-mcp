"""
verify/dk_company.py

danish_company_verify_v1 - official-registry company verification, Denmark.

One CVR number (8 digits) or company name in, one normalized and cited
answer out: canonical identity, legal status, latest recorded CVR changes,
and per-source observation timestamps with evidence links.

NO MOCK DATA. Fields Norric does not track return status "not_tracked".
Missing optional sources degrade to null plus a warning - never to a
fabricated value. See docs/no-fabrication-contract.md.

Danish labels (legal form, status, industry) are canonical as issued by
Erhvervsstyrelsen and are never translated; names and addresses are verbatim.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ingestion.cvr.normalize import normalize_cvr_number

log = logging.getLogger(__name__)

TOOL_NAME = "danish_company_verify_v1"

_ENTITY_SQL = """
    SELECT cvr_number, name, legal_form_code, legal_form_label, status_code,
           status_label, is_active, started_at, ceased_at, industry_code,
           industry_label, street, city, postcode, municipality_code,
           country_code, phone, email, website, source,
           registrering_fra, virkning_fra, first_seen_at, last_seen_at,
           last_updated_at
    FROM norric_dk_entities
    WHERE cvr_number = :cvr
"""

_NAME_SQL = """
    SELECT cvr_number, name, is_active
    FROM norric_dk_entities
    WHERE name ILIKE :pattern
    ORDER BY is_active DESC, name ASC
    LIMIT 5
"""

_CHANGES_SQL = """
    SELECT snapshot_date, field_name, old_value, new_value, source
    FROM norric_dk_field_changes
    WHERE entity_id = :cvr AND entity_type = 'company'
    ORDER BY snapshot_date DESC
    LIMIT 5
"""

_PIPELINES_SQL = """
    SELECT pipeline,
           MAX(completed_at) FILTER (WHERE status = 'success') AS last_success,
           MAX(started_at)                                     AS last_attempt
    FROM norric_pipeline_runs
    WHERE pipeline IN ('cvr_bulk', 'cvr_events', 'cvr_reconcile')
    GROUP BY pipeline
"""


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _optional(db: Session, sql: str, params: dict, label: str, warnings: list[str]):
    """Run an enrichment query; on failure degrade to None with a warning."""
    try:
        return db.execute(text(sql), params)
    except Exception as exc:
        log.warning("[%s] optional source %s failed: %s: %s",
                    params.get("cvr"), label, type(exc).__name__, exc)
        try:
            db.rollback()
        except Exception:
            pass
        warnings.append(f"{label}: source unavailable ({type(exc).__name__})")
        return None


def verify_company(db: Session, query: str) -> dict:
    """
    Verify a Danish company from the live CVR mirror. NEVER fabricates.

    Returns {data, sources, confidence, signals, warnings}.
    data.found=false when the CVR number/name is not in the mirror.
    data.match="ambiguous" with candidates when a name matches several companies.
    """
    warnings: list[str] = []
    signals: list[dict] = []
    query = (query or "").strip()
    if not query:
        raise ValueError("query must be a CVR number (8 digits) or a company name")

    if re.fullmatch(r"[\d\- ]{7,10}", query):
        cvr = normalize_cvr_number(query)
        entity = db.execute(text(_ENTITY_SQL), {"cvr": cvr}).fetchone()
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
                        {"cvr_number": r.cvr_number, "name": r.name,
                         "is_active": r.is_active}
                        for r in candidates
                    ],
                },
                "sources": ["cvr"],
                "confidence": 0.3,
                "signals": [],
                "warnings": warnings
                + ["ambiguous name match - retry with the CVR number of the intended company"],
            }
        if len(candidates) == 1:
            cvr = candidates[0].cvr_number
            entity = db.execute(text(_ENTITY_SQL), {"cvr": cvr}).fetchone()
        else:
            entity = None
            cvr = None

    if entity is None:
        data = {
            "query": query,
            "found": False,
            "match": "none",
            "verified": False,
        }
        if cvr:
            data["cvr_number"] = cvr
        return {
            "data": data,
            "sources": ["cvr"],
            "confidence": 0.3,
            "signals": [],
            "warnings": warnings
            + ["not found in the CVR registry mirror - the CVR number may be "
               "wrong or the entity outside current coverage"],
        }

    cvr = entity.cvr_number
    now = datetime.now(timezone.utc)

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
        "cvr_number": cvr,
        "name": entity.name,
        "legal_form": {"code": entity.legal_form_code,
                       "label": entity.legal_form_label},
        "registered_address": {
            "street": entity.street,
            "postcode": entity.postcode,
            "city": entity.city,
            "municipality_code": entity.municipality_code,
            "country_code": entity.country_code,
        },
        "industry": {"code": entity.industry_code, "label": entity.industry_label},
        "contact": {"phone": entity.phone, "email": entity.email,
                    "website": entity.website},
        "registry_source": entity.source,
        "registry_first_seen_at": _iso(entity.first_seen_at),
        "registry_last_confirmed_at": _iso(entity.last_seen_at),
    }
    legal_status = {
        "is_active": entity.is_active,
        "status_code": entity.status_code,
        "status_label": entity.status_label,
        "started_at": _iso(entity.started_at),
        "ceased_at": _iso(entity.ceased_at),
        "registrering_fra": _iso(entity.registrering_fra),
        "virkning_fra": _iso(entity.virkning_fra),
    }
    if not entity.is_active:
        signals.append({"key": "ceased", "label": "Virksomheden er ophørt",
                        "value": _iso(entity.ceased_at), "source": "cvr",
                        "direction": "risk"})

    # CVR does not publish VAT/employer registration in the open entities, and
    # Norric runs no Danish risk-score pipeline yet. Honest not_tracked/null.
    registrations = {
        "vat": {"status": "not_tracked"},
        "employer": {"status": "not_tracked"},
    }

    changes_r = _optional(db, _CHANGES_SQL, {"cvr": cvr}, "registry_changes", warnings)
    latest_changes = [
        {"snapshot_date": _iso(r.snapshot_date), "field": r.field_name,
         "from": r.old_value, "to": r.new_value, "source": r.source}
        for r in changes_r
    ] if changes_r is not None else []

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
        "country": "DK",
        "identity": identity,
        "legal_status": legal_status,
        "registrations": registrations,
        "risk": None,
        "latest_changes": latest_changes,
        "sources": sources_freshness,
        "evidence": {
            "basis": "Norric mirror of the Danish Central Business Register (CVR) "
                     "via Datafordeler fildownload and CVR_Events",
            "registry_last_confirmed_at": _iso(entity.last_seen_at),
            "reference_links": {
                "datafordeler_cvr": "https://datafordeler.dk/dataoversigt/det-centrale-virksomhedsregister-cvr/",
                "datafordeler_cvr_terms": "https://datafordeler.dk/vejledning/brugervilkaar/det-centrale-virksomhedsregister-cvr/",
            },
            "license": "CC BY 4.0 (Danish ground data) - attribution: Erhvervsstyrelsen / Datafordeleren",
        },
    }
    return {
        "data": data,
        "sources": ["cvr"],
        "confidence": confidence,
        "signals": signals,
        "warnings": warnings,
    }
