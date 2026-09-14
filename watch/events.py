"""
watch/events.py — watch event query + emission.

list_events_for_watch(): the replay/audit read behind norric_watch_events_v1
(and, later, a REST events endpoint). Tier history windows per spec §7:
Standard 7 days, Compliance full history with dead-letter kept 30 days.

The Phase 1 diff emission (comparing consecutive company_scores runs and
writing norric_watch_events rows) lands in this module with the worker PR.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

STANDARD_HISTORY_DAYS = 7
DEAD_LETTER_RETENTION_DAYS = 30


def _serialize_event(row) -> dict:
    return {
        "id": row.event_ref,
        "type": row.event_type,
        "orgnr": row.orgnr,
        "status": row.status,  # pending | delivered | dead
        "attempts": row.attempts,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        "dead_at": row.dead_at.isoformat() if row.dead_at else None,
        "last_http_status": row.last_http_status,
        "last_error": row.last_error,
        "payload": row.payload,
    }


def list_events_for_watch(
    db: Session,
    key_hash: str,
    tier: str,
    watch_ref: str,
    limit: int,
) -> Optional[list[dict]]:
    """
    Owner-scoped recent events for one watch, newest first.
    Returns None when the watch doesn't exist for this key (caller turns
    that into the same not-found envelope as update/delete).
    """
    owner = db.execute(
        text("SELECT 1 FROM norric_watches WHERE watch_ref = :wr AND key_hash = :kh"),
        {"wr": watch_ref, "kh": key_hash},
    ).fetchone()
    if owner is None:
        return None

    if tier == "standard":
        history_clause = f"e.occurred_at >= now() - interval '{STANDARD_HISTORY_DAYS} days'"
    else:
        # compliance: full history, except dead-letter rows age out after 30d
        history_clause = (
            f"(e.status <> 'dead' OR e.dead_at >= now() - interval "
            f"'{DEAD_LETTER_RETENTION_DAYS} days')"
        )

    rows = db.execute(
        text(f"""
            SELECT e.event_ref, e.event_type, e.orgnr, e.status, e.attempts,
                   e.occurred_at, e.delivered_at, e.dead_at,
                   e.last_http_status, e.last_error, e.payload
            FROM norric_watch_events e
            JOIN norric_watches w ON w.id = e.watch_id
            WHERE w.watch_ref = :wr AND {history_clause}
            ORDER BY e.occurred_at DESC
            LIMIT :lim
        """),
        {"wr": watch_ref, "lim": limit},
    ).fetchall()
    return [_serialize_event(r) for r in rows]
