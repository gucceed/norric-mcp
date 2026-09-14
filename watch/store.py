"""
watch/store.py — persistence for watches and watch events.

Raw SQL over the shared sync Session (ingestion.db), same style as the
rest of the codebase — no ORM models. Every read is scoped by key_hash:
a key can only ever see its own watches. The signing secret is written
once and never selected back out; create/rotate return it in-band.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .refs import new_signing_secret, new_watch_ref
from .validation import (
    entity_count,
    tier_entity_limit,
    validate_callback_url,
    validate_event_types,
    validate_filters,
)

# 50 consecutive failed deliveries pauses the watch (spec §6). Manual resume.
AUTO_PAUSE_FAILURE_THRESHOLD = 50


class WatchLimitError(ValueError):
    """Raised when a create/update would exceed the tier's entity budget."""


# ── Serialisation ────────────────────────────────────────────────────────────

def serialize_watch(row, include_secret: bool = False) -> dict:
    """
    The watch object shape from spec §4.1. signing_secret is only present
    on create/rotate responses — list/get/update never re-serve it.
    """
    out = {
        "id": row.watch_ref,
        "status": row.status,
        "event_types": list(row.event_types),
        "filters": row.filters if isinstance(row.filters, dict) else json.loads(row.filters),
        "callback_url": row.callback_url,
        "description": row.description,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "stats": {
            "events_sent": row.events_sent,
            "last_delivery_at": row.last_delivery_at.isoformat() if row.last_delivery_at else None,
            "consecutive_failures": row.consecutive_failures,
        },
    }
    if include_secret:
        out["signing_secret"] = row.signing_secret
    return out


# ── Tier budget ──────────────────────────────────────────────────────────────

def entity_budget_used(db: Session, key_hash: str, exclude_watch_ref: str | None = None) -> int:
    """Total watched entities across the key's watches (active and paused)."""
    sql = """
        SELECT filters FROM norric_watches
        WHERE key_hash = :kh
    """
    params: dict = {"kh": key_hash}
    if exclude_watch_ref:
        sql += " AND watch_ref <> :wr"
        params["wr"] = exclude_watch_ref
    rows = db.execute(text(sql), params).fetchall()
    total = 0
    for r in rows:
        f = r.filters if isinstance(r.filters, dict) else json.loads(r.filters)
        total += entity_count(f)
    return total


def _check_budget(db: Session, key_hash: str, tier: str, new_filters: dict,
                  exclude_watch_ref: str | None = None) -> None:
    limit = tier_entity_limit(tier)
    used = entity_budget_used(db, key_hash, exclude_watch_ref=exclude_watch_ref)
    requested = used + entity_count(new_filters)
    if requested > limit:
        raise WatchLimitError(
            f"watched-entity limit for tier {tier!r} is {limit}; "
            f"this change would bring the total to {requested}"
        )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_watch(
    db: Session,
    *,
    key_hash: str,
    tier: str,
    event_types,
    filters,
    callback_url: str,
    description: str | None = None,
    resolve_dns: bool = True,
) -> dict:
    """
    Create a watch. Returns the serialized watch INCLUDING the plaintext
    signing secret — the only response that ever contains it.
    """
    et = validate_event_types(event_types)
    f = validate_filters(filters)
    url = validate_callback_url(callback_url, resolve_dns=resolve_dns)
    _check_budget(db, key_hash, tier, f)

    secret = new_signing_secret()
    ref = new_watch_ref()
    row = db.execute(
        text("""
            INSERT INTO norric_watches (
                watch_ref, key_hash, event_types, filters,
                callback_url, signing_secret, description
            ) VALUES (
                :ref, :kh, :et, :f, :url, :secret, :descr
            )
            RETURNING id, watch_ref, status, event_types, filters, callback_url,
                      signing_secret, description, events_sent, last_delivery_at,
                      consecutive_failures, created_at, updated_at
        """),
        {
            "ref": ref,
            "kh": key_hash,
            "et": et,
            "f": json.dumps(f),
            "url": url,
            "secret": secret,
            "descr": (description or "").strip()[:500] or None,
        },
    ).fetchone()
    db.commit()
    return serialize_watch(row, include_secret=True)


def get_watch(db: Session, key_hash: str, watch_ref: str) -> Optional[dict]:
    """Owner-scoped fetch. Returns None for unknown OR foreign watch_refs —
    the two cases are indistinguishable to the caller on purpose."""
    row = db.execute(
        text("""
            SELECT watch_ref, status, event_types, filters, callback_url,
                   signing_secret, description, events_sent, last_delivery_at,
                   consecutive_failures, created_at, updated_at
            FROM norric_watches
            WHERE watch_ref = :wr AND key_hash = :kh
        """),
        {"wr": watch_ref, "kh": key_hash},
    ).fetchone()
    return serialize_watch(row) if row else None


def list_watches(db: Session, key_hash: str) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT watch_ref, status, event_types, filters, callback_url,
                   signing_secret, description, events_sent, last_delivery_at,
                   consecutive_failures, created_at, updated_at
            FROM norric_watches
            WHERE key_hash = :kh
            ORDER BY created_at DESC
        """),
        {"kh": key_hash},
    ).fetchall()
    return [serialize_watch(r) for r in rows]


_UPDATEABLE = {"event_types", "filters", "callback_url", "description", "status"}


def update_watch(
    db: Session,
    *,
    key_hash: str,
    tier: str,
    watch_ref: str,
    patch: dict,
    resolve_dns: bool = True,
) -> Optional[dict]:
    """
    Partial update. Unknown fields are rejected (a silently ignored field
    on a delivery mechanism is worse than a 400). status accepts
    'active' (resume) and 'paused'. Resuming resets consecutive_failures.
    Returns None when the watch doesn't exist for this key.
    """
    unknown = set(patch) - _UPDATEABLE
    if unknown:
        raise ValueError(
            f"unknown watch fields: {', '.join(sorted(unknown))}. "
            f"Updatable: {', '.join(sorted(_UPDATEABLE))}"
        )

    current = db.execute(
        text("""
            SELECT filters FROM norric_watches
            WHERE watch_ref = :wr AND key_hash = :kh
        """),
        {"wr": watch_ref, "kh": key_hash},
    ).fetchone()
    if current is None:
        return None

    sets: list[str] = ["updated_at = now()"]
    params: dict = {"wr": watch_ref, "kh": key_hash}

    if "event_types" in patch:
        params["et"] = validate_event_types(patch["event_types"])
        sets.append("event_types = :et")

    if "filters" in patch:
        f = validate_filters(patch["filters"])
        _check_budget(db, key_hash, tier, f, exclude_watch_ref=watch_ref)
        params["f"] = json.dumps(f)
        sets.append("filters = :f")

    if "callback_url" in patch:
        params["url"] = validate_callback_url(patch["callback_url"], resolve_dns=resolve_dns)
        sets.append("callback_url = :url")

    if "description" in patch:
        params["descr"] = (patch["description"] or "").strip()[:500] or None
        sets.append("description = :descr")

    if "status" in patch:
        status = str(patch["status"]).lower()
        if status not in ("active", "paused"):
            raise ValueError("status must be 'active' or 'paused'")
        params["st"] = status
        sets.append("status = :st")
        if status == "active":
            # Manual resume re-arms the auto-pause counter (spec §6).
            sets.append("consecutive_failures = 0")

    row = db.execute(
        text(f"""
            UPDATE norric_watches SET {', '.join(sets)}
            WHERE watch_ref = :wr AND key_hash = :kh
            RETURNING watch_ref, status, event_types, filters, callback_url,
                      signing_secret, description, events_sent, last_delivery_at,
                      consecutive_failures, created_at, updated_at
        """),
        params,
    ).fetchone()
    db.commit()
    return serialize_watch(row) if row else None


def delete_watch(db: Session, key_hash: str, watch_ref: str) -> bool:
    """Delete a watch and (via ON DELETE CASCADE) its events. False when the
    watch didn't exist for this key."""
    row = db.execute(
        text("""
            DELETE FROM norric_watches
            WHERE watch_ref = :wr AND key_hash = :kh
            RETURNING id
        """),
        {"wr": watch_ref, "kh": key_hash},
    ).fetchone()
    db.commit()
    return row is not None


def rotate_secret(db: Session, key_hash: str, watch_ref: str) -> Optional[str]:
    """Rotate the signing secret. Returns the new plaintext secret (shown
    once), or None when the watch doesn't exist for this key."""
    secret = new_signing_secret()
    row = db.execute(
        text("""
            UPDATE norric_watches
            SET signing_secret = :secret, updated_at = now()
            WHERE watch_ref = :wr AND key_hash = :kh
            RETURNING watch_ref
        """),
        {"secret": secret, "wr": watch_ref, "kh": key_hash},
    ).fetchone()
    db.commit()
    return secret if row else None


# ── Delivery bookkeeping ─────────────────────────────────────────────────────

def record_delivery(db: Session, watch_ref: str, success: bool) -> dict:
    """
    Update per-watch delivery stats after a delivery attempt resolves.

    success=True  → events_sent+1, last_delivery_at, failures reset.
    success=False → consecutive_failures+1; at AUTO_PAUSE_FAILURE_THRESHOLD
                    the watch flips to 'paused' (auto-pause, spec §6) so one
                    dead endpoint can't degrade the queue for everyone.

    Returns {"paused_now": bool, "consecutive_failures": int}.
    """
    if success:
        row = db.execute(
            text("""
                UPDATE norric_watches
                SET events_sent = events_sent + 1,
                    last_delivery_at = now(),
                    consecutive_failures = 0,
                    updated_at = now()
                WHERE watch_ref = :wr
                RETURNING consecutive_failures, status
            """),
            {"wr": watch_ref},
        ).fetchone()
        db.commit()
        return {
            "paused_now": False,
            "consecutive_failures": row.consecutive_failures if row else 0,
        }

    row = db.execute(
        text("""
            UPDATE norric_watches
            SET consecutive_failures = consecutive_failures + 1,
                status = CASE
                    WHEN consecutive_failures + 1 >= :threshold THEN 'paused'
                    ELSE status
                END,
                updated_at = now()
            WHERE watch_ref = :wr
            RETURNING consecutive_failures, status
        """),
        {"wr": watch_ref, "threshold": AUTO_PAUSE_FAILURE_THRESHOLD},
    ).fetchone()
    db.commit()
    if not row:
        return {"paused_now": False, "consecutive_failures": 0}
    return {
        "paused_now": row.status == "paused"
        and row.consecutive_failures >= AUTO_PAUSE_FAILURE_THRESHOLD,
        "consecutive_failures": row.consecutive_failures,
    }
