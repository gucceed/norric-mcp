"""Normalized Swedish company change events from Norric's registry snapshots.

Only persisted source changes are returned. The tool never treats a company's
first appearance in Norric's mirror as its legal registration date.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

TOOL_NAME = "swedish_company_changes_v1"
ALLOWED_EVENT_TYPES = {
    "new_registration", "closure", "rename", "address_change", "merger"
}

_CHANGES_SQL = """
    SELECT c.entity_id AS orgnr, c.snapshot_date, c.field_name,
           c.old_value, c.new_value, e.name, e.orgform, e.is_active,
           e.orgnr_display, e.last_seen_at
    FROM norric_field_changes c
    LEFT JOIN norric_entities e
      ON replace(e.orgnr, '-', '') = replace(c.entity_id, '-', '')
    WHERE c.entity_type = 'company'
      AND c.source = 'bolagsverket'
      AND c.snapshot_date >= :since_date
      AND (:orgnr IS NULL OR replace(c.entity_id, '-', '') = :orgnr)
    ORDER BY c.snapshot_date DESC, c.entity_id ASC, c.field_name ASC
    LIMIT :query_limit
"""

_PIPELINE_SQL = """
    SELECT MAX(completed_at) FILTER (WHERE status = 'success') AS last_success,
           MAX(started_at) AS last_attempt
    FROM norric_pipeline_runs
    WHERE pipeline = 'bolagsverket_bulk'
"""


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _normalize_orgnr(value: str) -> str:
    clean = str(value or "").replace("-", "").replace(" ", "")
    if len(clean) == 10 and clean.isdigit():
        return f"{clean[:6]}-{clean[6:]}"
    return str(value)


def _event_type(field: str, old_value, new_value) -> Optional[str]:
    field = (field or "").lower()
    if field in {"name", "organisationsnamn"}:
        return "rename"
    if field in {"street", "city", "postcode", "kommunkod", "county", "raw_address"}:
        return "address_change"
    if field == "is_active" and str(new_value).lower() in {"false", "0", "no"}:
        return "closure"
    if field in {"deregistered_at", "avregistreringsdatum"} and new_value:
        return "closure"
    if field in {"merger", "merger_status", "avregistreringsorsak", "restructuring_status"}:
        value = f"{old_value or ''} {new_value or ''}".lower()
        if any(token in value for token in ("fusion", "merger", "absorption")):
            return "merger"
    if field in {"registered_at", "registreringsdatum"} and not old_value and new_value:
        return "new_registration"
    return None


def company_changes(
    db: Session,
    *,
    days: int = 7,
    event_types: Optional[Iterable[str]] = None,
    limit: int = 25,
    orgnr: Optional[str] = None,
) -> dict:
    """Return normalized, cited registry changes. Never fabricates event classes."""
    if not 1 <= days <= 30:
        raise ValueError("days must be between 1 and 30")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    selected = set(event_types or ALLOWED_EVENT_TYPES)
    unknown = selected - ALLOWED_EVENT_TYPES
    if unknown:
        raise ValueError(f"unsupported event_types: {', '.join(sorted(unknown))}")
    orgnr_digits = None
    if orgnr:
        orgnr_digits = str(orgnr).replace("-", "").replace(" ", "")
        if len(orgnr_digits) != 10 or not orgnr_digits.isdigit():
            raise ValueError("orgnr must contain 10 digits")

    since_date = datetime.now(timezone.utc).date().fromordinal(
        datetime.now(timezone.utc).date().toordinal() - days
    )
    rows = db.execute(text(_CHANGES_SQL), {
        "since_date": since_date,
        "orgnr": orgnr_digits,
        "query_limit": min(limit * 12, 1200),
    })

    grouped: OrderedDict[tuple, dict] = OrderedDict()
    observed_types: set[str] = set()
    for row in rows:
        kind = _event_type(row.field_name, row.old_value, row.new_value)
        if not kind or kind not in selected:
            continue
        observed_types.add(kind)
        normalized = _normalize_orgnr(row.orgnr_display or row.orgnr)
        key = (normalized, _iso(row.snapshot_date), kind)
        event = grouped.setdefault(key, {
            "event_type": kind,
            "orgnr": normalized,
            "company_name": row.name,
            "orgform": row.orgform,
            "is_active": row.is_active,
            "effective_on": _iso(row.snapshot_date),
            "detected_on": _iso(row.snapshot_date),
            "changes": [],
            "source": "bolagsverket_bulk",
            "source_last_confirmed_at": _iso(row.last_seen_at),
            "evidence": {
                "basis": "Norric Bolagsverket registry snapshot diff",
                "reference_links": {
                    "bolagsverket_foretagsinfo": "https://foretagsinfo.bolagsverket.se/sok-foretagsinformation-web/",
                    "allabolag": f"https://www.allabolag.se/{normalized.replace('-', '')}",
                },
            },
        })
        event["changes"].append({
            "field": row.field_name,
            "from": row.old_value,
            "to": row.new_value,
        })
        if len(grouped) >= limit and key == next(reversed(grouped)):
            # Keep collecting sibling fields for the current event; later events
            # are discarded below to preserve a deterministic limit.
            pass

    events = list(grouped.values())[:limit]
    pipeline = db.execute(text(_PIPELINE_SQL)).fetchone()
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

    freshness = {
        "pipeline": "bolagsverket_bulk",
        "last_success": _iso(pipeline.last_success) if pipeline else None,
        "last_attempt": _iso(pipeline.last_attempt) if pipeline else None,
    }
    return {
        "data": {
            "window": {"days": days, "since": since_date.isoformat()},
            "filters": {
                "event_types": sorted(selected),
                "orgnr": _normalize_orgnr(orgnr_digits) if orgnr_digits else None,
                "limit": limit,
            },
            "count": len(events),
            "events": events,
            "source_freshness": freshness,
            "event_type_contract": sorted(ALLOWED_EVENT_TYPES),
        },
        "sources": ["bolagsverket"],
        "confidence": 0.95 if freshness["last_success"] else 0.7,
        "warnings": warnings,
    }
