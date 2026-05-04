"""
DB-backed API key validation with Redis cache.

Lookup order:
  1. NORRIC_API_KEYS env var (plain keys, no DB/Redis)  — caller handles this
  2. Redis cache  GET api_key:{sha256}
  3. DB query     SELECT tier, status FROM api_keys WHERE key_hash = $1

Cache TTLs:
  valid keys : 300 s  (5 min)
  revoked    : 60 s   (tight upper bound on revocation propagation)

Redis is optional — if REDIS_URL is unset or Redis is down the lookup
falls through to DB on every request.  This is safe; Redis is a perf
optimisation only.

last_used_at is updated fire-and-forget in a background thread so it
never adds latency to the request path.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Optional

log = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "")
_redis_client = None
_redis_unavailable = False  # latched True on first connection failure


def _get_redis():
    global _redis_client, _redis_unavailable
    if _redis_unavailable or not _REDIS_URL:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        _redis_client = redis.from_url(_REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        _redis_client.ping()
        return _redis_client
    except Exception as exc:
        log.warning(f"[AUTH] Redis unavailable ({exc}) — falling back to DB only")
        _redis_unavailable = True
        return None


def _sha256(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _cache_key(key_hash: str) -> str:
    return f"api_key:{key_hash}"


def _update_last_used(key_hash: str) -> None:
    """Fire-and-forget: update last_used_at in DB without blocking the request."""
    def _run():
        try:
            from ingestion.db import Session
            from sqlalchemy import text
            db = Session()
            try:
                db.execute(
                    text("UPDATE api_keys SET last_used_at = now() WHERE key_hash = :h"),
                    {"h": key_hash},
                )
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            log.debug(f"[AUTH] last_used_at update failed: {exc}")

    threading.Thread(target=_run, daemon=True).start()


def lookup_key(raw_key: str) -> Optional[tuple[str, str]]:
    """
    Validate raw_key against Redis cache then DB.

    Returns (tier, source) where source is 'cache' or 'db',
    or None if the key is invalid/revoked.
    """
    key_hash = _sha256(raw_key)
    cache_k = _cache_key(key_hash)

    # ── Redis cache ────────────────────────────────────────────────────────────
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(cache_k)
            if cached is not None:
                value = cached.decode() if isinstance(cached, bytes) else cached
                if value.startswith("valid:"):
                    tier = value[6:]
                    _update_last_used(key_hash)
                    return (tier, "cache")
                else:  # "revoked"
                    return None
        except Exception as exc:
            log.debug(f"[AUTH] Redis get failed: {exc}")

    # ── DB lookup ──────────────────────────────────────────────────────────────
    try:
        from ingestion.db import Session
        from sqlalchemy import text
        db = Session()
        try:
            row = db.execute(
                text("SELECT tier, status FROM api_keys WHERE key_hash = :h LIMIT 1"),
                {"h": key_hash},
            ).fetchone()
        finally:
            db.close()
    except Exception as exc:
        log.error(f"[AUTH] DB lookup failed: {exc}")
        return None

    if row is None or row.status != "active":
        # Cache the miss/revocation
        if r is not None:
            try:
                r.set(cache_k, "revoked", ex=60)
            except Exception:
                pass
        return None

    # Cache the hit
    if r is not None:
        try:
            r.set(cache_k, f"valid:{row.tier}", ex=300)
        except Exception:
            pass

    _update_last_used(key_hash)
    return (row.tier, "db")
