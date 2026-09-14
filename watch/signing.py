"""
watch/signing.py — HMAC-SHA256 webhook payload signing.

Wire format (Stripe-compatible, so platform integrators can reuse their
existing verification code):

    X-Norric-Signature: t=1726410000,v1=9f86d08...

where v1 = HMAC_SHA256(signing_secret, "{t}.{raw_body}").

At-least-once delivery means customers must also dedupe on
X-Norric-Event-Id; the timestamp tolerance below is for replay
protection on their side, not ordering on ours.
"""
from __future__ import annotations

import hashlib
import hmac
import time

DEFAULT_TOLERANCE_SECONDS = 300


def sign_body(secret: str, timestamp: int, body: bytes) -> str:
    """Hex HMAC-SHA256 of "{timestamp}.{body}" under the watch secret."""
    msg = str(timestamp).encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def signature_header(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """Build the X-Norric-Signature header value for an outbound delivery."""
    ts = int(time.time()) if timestamp is None else int(timestamp)
    return f"t={ts},v1={sign_body(secret, ts, body)}"


def verify_signature_header(
    secret: str,
    header: str,
    body: bytes,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: int | None = None,
) -> bool:
    """
    Verify an X-Norric-Signature header against a received body.

    Exposed (and unit-tested) so the customer-facing verification snippet
    in the docs exercises the exact same comparison we ship. Constant-time
    comparison; rejects stale timestamps outside the tolerance window.
    """
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        v1 = parts["v1"]
    except (ValueError, KeyError, AttributeError):
        return False

    now_ts = int(time.time()) if now is None else int(now)
    if abs(now_ts - ts) > tolerance_seconds:
        return False

    expected = sign_body(secret, ts, body)
    return hmac.compare_digest(expected, v1)
