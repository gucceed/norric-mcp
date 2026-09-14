"""
watch/api.py — Norric Watch REST API (spec §4.1).

    POST   /api/v1/watches                 create (returns signing secret once)
    GET    /api/v1/watches                 list this key's watches
    GET    /api/v1/watches/{watch_ref}     inspect one
    PATCH  /api/v1/watches/{watch_ref}     update filters / url / status / description
    DELETE /api/v1/watches/{watch_ref}     delete
    POST   /api/v1/watches/{watch_ref}/test           send a signed test event
    POST   /api/v1/watches/{watch_ref}/rotate-secret  rotate the signing secret

Auth rides the outer ASGI middleware (server.py): it has already validated
the key and stamped scope["norric_tier"] / scope["norric_key_hash"] before
anything here runs. Free tier gets 403 — Watch is a paid-tier surface.
Every query is owner-scoped by key_hash; unknown and foreign watch_refs are
indistinguishable 404s.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import store
from .deliver import post_signed, test_event_payload
from .refs import new_event_ref
from .validation import tier_allows_watch

app = FastAPI(title="Norric Watch API", version="1.0.0")


class CreateWatchRequest(BaseModel):
    event_types: list[str]
    filters: Optional[dict] = None
    callback_url: str
    description: Optional[str] = Field(default=None, max_length=500)


class UpdateWatchRequest(BaseModel):
    event_types: Optional[list[str]] = None
    filters: Optional[dict] = None
    callback_url: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=500)
    status: Optional[str] = None  # "active" (resume) | "paused"

    def patch(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


def _get_db():
    from ingestion.db import Session
    db = Session()
    try:
        yield db
    finally:
        db.close()


def _owner(request: Request) -> tuple[str, str]:
    """
    (key_hash, tier) from the outer auth middleware's scope stamps.
    403 when the tier can't watch or the key has no DB identity
    (master/env keys authenticate but own no watches).
    """
    tier = request.scope.get("norric_tier", "")
    key_hash = request.scope.get("norric_key_hash", "")
    if not tier_allows_watch(tier):
        raise HTTPException(
            status_code=403,
            detail="Watch requires a Standard or Compliance tier API key.",
        )
    if not key_hash:
        raise HTTPException(
            status_code=403,
            detail="Watch requires a DB-issued API key (norric.io/api-keys).",
        )
    return key_hash, tier


@app.post("/api/v1/watches", status_code=201)
def create_watch(req: CreateWatchRequest, request: Request, db=Depends(_get_db)):
    key_hash, tier = _owner(request)
    try:
        return store.create_watch(
            db,
            key_hash=key_hash,
            tier=tier,
            event_types=req.event_types,
            filters=req.filters,
            callback_url=req.callback_url,
            description=req.description,
        )
    except store.WatchLimitError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/watches")
def list_watches(request: Request, db=Depends(_get_db)):
    key_hash, _ = _owner(request)
    return {"watches": store.list_watches(db, key_hash)}


@app.get("/api/v1/watches/{watch_ref}")
def get_watch(watch_ref: str, request: Request, db=Depends(_get_db)):
    key_hash, _ = _owner(request)
    watch = store.get_watch(db, key_hash, watch_ref)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    return watch


@app.patch("/api/v1/watches/{watch_ref}")
def update_watch(watch_ref: str, req: UpdateWatchRequest, request: Request, db=Depends(_get_db)):
    key_hash, tier = _owner(request)
    try:
        watch = store.update_watch(
            db,
            key_hash=key_hash,
            tier=tier,
            watch_ref=watch_ref,
            patch=req.patch(),
        )
    except store.WatchLimitError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    return watch


@app.delete("/api/v1/watches/{watch_ref}")
def delete_watch(watch_ref: str, request: Request, db=Depends(_get_db)):
    key_hash, _ = _owner(request)
    if not store.delete_watch(db, key_hash, watch_ref):
        raise HTTPException(status_code=404, detail="watch not found")
    return {"deleted": watch_ref}


@app.post("/api/v1/watches/{watch_ref}/test")
def send_test_event(watch_ref: str, request: Request, db=Depends(_get_db)):
    """
    Deliver one signed norric.test event to the watch's callback URL,
    synchronously, and record delivery stats. Single attempt — retries are
    for pipeline events, not liveness checks.
    """
    key_hash, _ = _owner(request)
    row = store.get_watch_row(db, key_hash, watch_ref)
    if row is None:
        raise HTTPException(status_code=404, detail="watch not found")

    event_ref = new_event_ref()
    payload = test_event_payload(watch_ref, event_ref)
    status, error = post_signed(
        row.callback_url, row.signing_secret, event_ref, "norric.test", payload
    )
    delivered = status is not None and 200 <= status < 300
    stats = store.record_delivery(db, watch_ref, delivered)
    return {
        "event_id": event_ref,
        "delivered": delivered,
        "http_status": status,
        "error": error,
        "watch_stats": stats,
    }


@app.post("/api/v1/watches/{watch_ref}/rotate-secret")
def rotate_secret(watch_ref: str, request: Request, db=Depends(_get_db)):
    key_hash, _ = _owner(request)
    secret = store.rotate_secret(db, key_hash, watch_ref)
    if secret is None:
        raise HTTPException(status_code=404, detail="watch not found")
    return {"id": watch_ref, "signing_secret": secret}
