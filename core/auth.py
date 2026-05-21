"""
core/auth.py

Master-key verification. Argon2 hash check against NORRIC_MASTER_KEY_HASH.

This module deliberately does NOT touch DB, Redis, or the multi-key
norric_auth flow — that's core/db_auth.py's job. It answers one question:
does this raw key argon2-verify against the single env-pinned master hash?

The middleware at server.py:_NorricAuthMiddleware tries this fast-path
first. On hit, the request is authenticated as the all-tiers 'master'
identity and the DB lookup is skipped. On miss, the middleware falls
through to the existing norric_auth flow.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_MASTER_KEY_HASH_ENV = "NORRIC_MASTER_KEY_HASH"

_hasher = None  # cached PasswordHasher; lazy so argon2-cffi is optional at import


def _get_hasher():
    global _hasher
    if _hasher is None:
        from argon2 import PasswordHasher
        _hasher = PasswordHasher()
    return _hasher


def verify_master_key(raw_key: str) -> bool:
    """
    Return True iff raw_key argon2-verifies against $NORRIC_MASTER_KEY_HASH.

    Returns False on: missing env var, missing/empty raw_key, hash format
    error, or verification mismatch. Does NOT raise — callers branch on
    the bool only.
    """
    if not raw_key:
        return False
    expected = os.environ.get(_MASTER_KEY_HASH_ENV, "")
    if not expected:
        return False
    try:
        from argon2.exceptions import InvalidHashError, VerifyMismatchError
        _get_hasher().verify(expected, raw_key)
        return True
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        log.error("[AUTH] NORRIC_MASTER_KEY_HASH is not a valid argon2 hash")
        return False
    except Exception as exc:
        log.error(f"[AUTH] master key verify failed: {type(exc).__name__}: {exc}")
        return False
