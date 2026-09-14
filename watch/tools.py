"""
watch/tools.py — Norric Watch MCP tools (spec §4.2).

    norric_watch_create_v1   create a watch (returns signing secret once)
    norric_watch_list_v1     list this key's watches with delivery stats
    norric_watch_update_v1   change filters, url, pause/resume
    norric_watch_delete_v1   delete
    norric_watch_events_v1   recent events for a watch (replay/audit;
                             Standard: 7 days — Compliance: full history,
                             dead-letter kept 30 days)

The differentiator: a platform's agent can self-subscribe mid-conversation —
norric_watch_create_v1(orgnrs=["556012-3456"], event_types=[...],
callback_url=...) and the monitoring exists. No dashboard, no human.

Auth: the outer ASGI middleware has already validated the API key for the
/mcp path; these tools read its scope stamps via the FastMCP HTTP request
context. Free tier is denied (Watch is paid-only, spec §7).

Wire into server.py with:
    from watch.tools import register_watch_tools
    register_watch_tools(mcp)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from . import store
from .events import list_events_for_watch
from .validation import DEFAULT_MIN_SCORE_DELTA, tier_allows_watch

log = logging.getLogger(__name__)


def _get_db():
    from ingestion.db import Session
    return Session()


def _caller() -> tuple[str, str]:
    """
    (key_hash, tier) for the calling API key, from the outer middleware's
    scope stamps on the current HTTP request. Raises PermissionError for
    free tier and for keys with no DB identity.
    """
    from fastmcp.server.dependencies import get_http_request

    try:
        req = get_http_request()
    except Exception as e:
        raise PermissionError("watch tools require an HTTP request context") from e

    tier = req.scope.get("norric_tier", "")
    key_hash = req.scope.get("norric_key_hash", "")
    if not tier_allows_watch(tier):
        raise PermissionError(
            "Norric Watch requires a Standard or Compliance tier API key."
        )
    if not key_hash:
        raise PermissionError("Norric Watch requires a DB-issued API key.")
    return key_hash, tier


def _wrap(**kw) -> dict:
    """The standard Norric envelope — lazy import avoids the server.py cycle."""
    from server import wrap
    return wrap(**kw)




def _get_filters(watch_ref: str, key_hash: str) -> Optional[dict]:
    db = _get_db()
    try:
        watch = store.get_watch(db, key_hash, watch_ref)
        return watch["filters"] if watch else None
    finally:
        db.close()


# ── Tools ────────────────────────────────────────────────────────────────────

async def norric_watch_create(
    event_types: list[str],
    callback_url: str,
    orgnrs: Optional[list[str]] = None,
    min_score_delta: int = DEFAULT_MIN_SCORE_DELTA,
    description: Optional[str] = None,
) -> dict:
    """
    Create a Norric Watch: push a signed webhook to callback_url when a
    watched company's Kreditvakt data changes.

    Args:
        event_types: one or more of: company.risk_tier_changed,
            company.score_changed, company.debt_signal_new,
            company.bankruptcy_status_changed
        callback_url: HTTPS endpoint that receives signed POSTs
            (X-Norric-Signature: t=...,v1=... — HMAC-SHA256, like Stripe)
        orgnrs: Swedish org numbers to watch (e.g. ["556012-3456"])
        min_score_delta: minimum 0-20 risk_score movement that fires
            company.score_changed (default 3)
        description: free-text label for this watch

    Returns the watch object including signing_secret — shown ONCE.
    Events emit after the daily scoring beat (~05:30 Europe/Stockholm);
    delivery is at-least-once, dedupe on X-Norric-Event-Id.
    """
    key_hash, tier = _caller()
    filters = {"orgnrs": orgnrs or [], "min_score_delta": min_score_delta}

    def _create():
        db = _get_db()
        try:
            return store.create_watch(
                db, key_hash=key_hash, tier=tier, event_types=event_types,
                filters=filters, callback_url=callback_url,
                description=description,
            )
        finally:
            db.close()

    try:
        watch = await asyncio.to_thread(_create)
    except store.WatchLimitError as e:
        raise ValueError(str(e)) from e
    return _wrap(
        tool="norric_watch_create_v1",
        source=["norric_watch"],
        confidence=1.0,
        ttl=0,
        data={"watch": watch},
        warnings=["signing_secret is shown once — store it now."],
    )


async def norric_watch_list() -> dict:
    """List your API key's watches with delivery stats (events_sent,
    last_delivery_at, consecutive_failures) and status (active/paused).
    A watch auto-pauses after 50 consecutive failed deliveries; resume
    with norric_watch_update_v1(status="active")."""
    key_hash, _ = _caller()

    def _list():
        db = _get_db()
        try:
            return store.list_watches(db, key_hash)
        finally:
            db.close()

    watches = await asyncio.to_thread(_list)
    return _wrap(
        tool="norric_watch_list_v1",
        source=["norric_watch"],
        confidence=1.0,
        ttl=0,
        data={"watches": watches, "count": len(watches)},
    )


async def norric_watch_update(
    watch_id: str,
    event_types: Optional[list[str]] = None,
    orgnrs: Optional[list[str]] = None,
    min_score_delta: Optional[int] = None,
    callback_url: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """
    Update a watch. Only the fields you pass change.

    Args:
        watch_id: watch_... id from create/list
        event_types: replacement event type list
        orgnrs: replacement watched-orgnr list
        min_score_delta: replacement score-delta threshold (1-20)
        callback_url: replacement HTTPS callback URL
        description: replacement label
        status: "paused" to stop delivery, "active" to resume (resume
            resets the consecutive-failure counter that auto-pauses at 50)
    """
    key_hash, tier = _caller()
    patch: dict = {}
    if event_types is not None:
        patch["event_types"] = event_types
    if orgnrs is not None or min_score_delta is not None:
        # Merge over the current filters so a partial update (only orgnrs,
        # or only the delta) keeps the other half. A missing watch surfaces
        # as the not-found envelope below, same as any other patch.
        current = await asyncio.to_thread(_get_filters, watch_id, key_hash)
        if current is None:
            return _wrap(
                tool="norric_watch_update_v1", source=["norric_watch"],
                confidence=1.0, ttl=0, data={"watch": None},
                warnings=[f"watch {watch_id} not found for this API key"],
            )
        patch["filters"] = {
            "orgnrs": orgnrs if orgnrs is not None else current.get("orgnrs", []),
            "min_score_delta": (
                min_score_delta if min_score_delta is not None
                else current.get("min_score_delta", DEFAULT_MIN_SCORE_DELTA)
            ),
        }
    if callback_url is not None:
        patch["callback_url"] = callback_url
    if description is not None:
        patch["description"] = description
    if status is not None:
        patch["status"] = status
    if not patch:
        raise ValueError("nothing to update — pass at least one field")

    def _update():
        db = _get_db()
        try:
            return store.update_watch(
                db, key_hash=key_hash, tier=tier, watch_ref=watch_id, patch=patch,
            )
        finally:
            db.close()

    try:
        watch = await asyncio.to_thread(_update)
    except store.WatchLimitError as e:
        raise ValueError(str(e)) from e
    if watch is None:
        return _wrap(
            tool="norric_watch_update_v1", source=["norric_watch"],
            confidence=1.0, ttl=0, data={"watch": None},
            warnings=[f"watch {watch_id} not found for this API key"],
        )
    return _wrap(
        tool="norric_watch_update_v1", source=["norric_watch"],
        confidence=1.0, ttl=0, data={"watch": watch},
    )


async def norric_watch_delete(watch_id: str) -> dict:
    """Delete a watch and its event history. Immediate; no delivery
    attempt is made after deletion."""
    key_hash, _ = _caller()

    def _delete():
        db = _get_db()
        try:
            return store.delete_watch(db, key_hash, watch_id)
        finally:
            db.close()

    deleted = await asyncio.to_thread(_delete)
    warnings = [] if deleted else [f"watch {watch_id} not found for this API key"]
    return _wrap(
        tool="norric_watch_delete_v1", source=["norric_watch"],
        confidence=1.0, ttl=0,
        data={"deleted": watch_id if deleted else None},
        warnings=warnings,
    )


async def norric_watch_events(watch_id: str, limit: int = 50) -> dict:
    """
    Recent events for a watch — delivery replay/audit. Includes
    dead-lettered events (status "dead", kept 30 days). Standard tier
    sees 7 days of history; Compliance sees full history.

    Args:
        watch_id: watch_... id
        limit: max events to return (1-200, default 50)
    """
    key_hash, tier = _caller()
    limit = max(1, min(int(limit), 200))

    def _events():
        db = _get_db()
        try:
            return list_events_for_watch(db, key_hash, tier, watch_id, limit)
        finally:
            db.close()

    events = await asyncio.to_thread(_events)
    if events is None:
        return _wrap(
            tool="norric_watch_events_v1", source=["norric_watch"],
            confidence=1.0, ttl=0, data={"events": None},
            warnings=[f"watch {watch_id} not found for this API key"],
        )
    return _wrap(
        tool="norric_watch_events_v1", source=["norric_watch"],
        confidence=1.0, ttl=0,
        data={"events": events, "count": len(events), "history_days": 7 if tier == "standard" else None},
    )


def register_watch_tools(mcp) -> None:
    """
    Register the five Watch tools with a FastMCP instance.

    Usage in server.py:
        from watch.tools import register_watch_tools
        register_watch_tools(mcp)
    """
    mcp.tool(name="norric_watch_create_v1")(norric_watch_create)
    mcp.tool(name="norric_watch_list_v1")(norric_watch_list)
    mcp.tool(name="norric_watch_update_v1")(norric_watch_update)
    mcp.tool(name="norric_watch_delete_v1")(norric_watch_delete)
    mcp.tool(name="norric_watch_events_v1")(norric_watch_events)
