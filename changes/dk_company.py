"""Normalized Danish company change events from Norric's CVR mirror.

Only persisted source changes are returned. The tool never treats a company's
first appearance in Norric's mirror as its legal registration date.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ingestion.cvr.normalize import normalize_cvr_number

TOOL_NAME = "danish_company_changes_v1"
ALLOWED_EVENT_TYPES = {
    "new_registration", "closure", "rename", "address_change", "merger"
}

_CHANGES_SQL = """
    SELECT c.entity_id AS cvr_number, c.snapshot_date, c.field_name,
           c.old_value, c.new_value, c.source AS change_source,
           e.name, e.legal_form_code, e.is_active, e.last_seen_at
    FROM norric_dk_field_changes c
    LEFT JOIN norric_dk_entities e
      ON e.cvr_number = c.entity_id
    WHERE c.entity_type = 'company'
      AND c.snapshot_date >= :since_date
      AND (:cvr IS NULL OR c.entity_id = :cvr)
    ORDER BY c.snapshot_date DESC, c.entity_id ASC, c.field_name ASC
    LIMIT :query_limit
"""

_PIPELINE_SQL = """
    SELECT pipeline,
           MAX(completed_at) FILTER (WHERE status = 'success') AS last_success,
           MAX(started_at) AS last_attempt
    FROM norric_pipeline_runs
    WHERE pipeline IN ('cvr_bulk', 'cvr_events')
    GROUP BY pipeline
"""


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _event_type(field: str, old_value, new_value) -> Optional[str]:
    field = (field or "").lower()
    if field in {"name", "navn", "virksomhedsnavn"}:
        return "rename"
    if field in {"street", "city", "postcode", "municipality_code",
                 "country_code", "raw_address"}:
        return "address_change"
    if field == "is_active" and str(new_value).lower() in {"false", "0", "no"}:
        return "closure"
    if field in {"ceased_at", "ophorsdato", "ophørsdato"} and new_value:
        return "closure"
    if field in {"status_code", "status_label", "legal_form_code",
                 "legal_form_label", "virksomhedsstatus"}:
        value = f"{old_value or ''} {new_value or ''}".lower()
        if any(token in value for token in ("fusion", "merger", "sammensmeltning")):
            return "merger"
        if any(token in value for token in ("ophør", "ophort", "ophoert",
                                            "opløsning", "oploesning",
                                            "konkurs", "dissolved", "ceased")):
            return "closure"
    if field in {"started_at", "startdato"} and not old_value and new_value:
        return "new_registration"
    return None


def company_changes(
    db: Session,
    *,
    days: int = 7,
    event_types: Optional[Iterable[str]] = None,
    limit: int = 25,
    cvr_number: Optional[str] = None,
) -> dict:
    """Return normalized, cited CVR registry changes. Never fabricates event classes."""
    if not 1 <= days <= 30:
        raise ValueError("days must be between 1 and 30")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    selected = set(event_types or ALLOWED_EVENT_TYPES)
    unknown = selected - ALLOWED_EVENT_TYPES
    if unknown:
        raise ValueError(f"unsupported event_types: {', '.join(sorted(unknown))}")
    cvr = None
    if cvr_number:
        cvr = normalize_cvr_number(cvr_number)

    since_date = datetime.now(timezone.utc).date().fromordinal(
        datetime.now(timezone.utc).date().toordinal() - days
    )
    rows = db.execute(text(_CHANGES_SQL), {
        "since_date": since_date,
        "cvr": cvr,
        "query_limit": min(limit * 12, 1200),
    })

    grouped: OrderedDict[tuple, dict] = OrderedDict()
    observed_types: set[str] = set()
    for row in rows:
        kind = _event_type(row.field_name, row.old_value, row.new_value)
        if not kind or kind not in selected:
            continue
        observed_types.add(kind)
        key = (row.cvr_number, _iso(row.snapshot_date), kind)
        event = grouped.setdefault(key, {
            "event_type": kind,
            "cvr_number": row.cvr_number,
            "company_name": row.name,
            "legal_form_code": row.legal_form_code,
            "is_active": row.is_active,
            "effective_on": _iso(row.snapshot_date),
            "detected_on": _iso(row.snapshot_date),
            "changes": [],
            "source": row.change_source or "cvr",
            "source_last_confirmed_at": _iso(row.last_seen_at),
            "evidence": {
                "basis": "Norric CVR registry diff (bulk baseline + CVR_Events deltas)",
                "reference_links": {
                    "datafordeler_cvr": "https://datafordeler.dk/dataoversigt/det-centrale-virksomhedsregister-cvr/",
                },
                "license": "CC BY 4.0 (Danish ground data) - attribution: Erhvervsstyrelsen / Datafordeleren",
            },
        })
        event["changes"].append({
            "field": row.field_name,
            "from": row.old_value,
            "to": row.new_value,
        })

    events = list(grouped.values())[:limit]
    pipe_rows = db.execute(text(_PIPELINE_SQL)).fetchall()
    freshness = {
        r.pipeline: {"last_success": _iso(r.last_success),
                     "last_attempt": _iso(r.last_attempt)}
        for r in pipe_rows
    }

    warnings = []
    unavailable = selected & {"new_registration", "merger"} - observed_types
    if unavailable:
        warnings.append(
            "No source-backed " + ", ".join(sorted(unavailable))
            + " events were available in this window. Norric does not infer legal "
              "registration or merger status from first-seen dates or name changes."
        )
    if not events:
        warnings.append("No matching registry changes were recorded in this window.")

    any_success = any(f["last_success"] for f in freshness.values())
    return {
        "data": {
            "country": "DK",
            "window": {"days": days, "since": since_date.isoformat()},
            "filters": {
                "event_types": sorted(selected),
                "cvr_number": cvr,
                "limit": limit,
            },
            "count": len(events),
            "events": events,
            "source_freshness": freshness,
            "event_type_contract": sorted(ALLOWED_EVENT_TYPES),
        },
        "sources": ["cvr"],
        "confidence": 0.95 if any_success else 0.7,
        "warnings": warnings,
    }
