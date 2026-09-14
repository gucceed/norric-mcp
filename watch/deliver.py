"""
watch/deliver.py — signed webhook delivery.

post_signed() is the single outbound path: every delivery (test events now,
diff events from the Phase 1 worker) goes through it so headers, signing
and timeout policy stay identical. The Phase 1 delivery worker adds
retry/backoff scheduling on top of the event rows; this module owns the
wire format.

Wire contract (spec §5):
    X-Norric-Event-Id:   evt_...
    X-Norric-Event-Type: company.risk_tier_changed | norric.test | ...
    X-Norric-Signature:  t=<unix>,v1=<hmac-sha256 hex>
    X-Norric-Delivery:   <attempt number, 1-based>
Any 2xx counts as delivered; everything else is a failure.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from .signing import signature_header

DELIVERY_TIMEOUT_SECONDS = 10.0
USER_AGENT = "Norric-Watch/1.0 (+https://norric.io/docs)"


def build_headers(event_ref: str, event_type: str, secret: str, body: bytes,
                  attempt: int = 1) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Norric-Event-Id": event_ref,
        "X-Norric-Event-Type": event_type,
        "X-Norric-Signature": signature_header(secret, body),
        "X-Norric-Delivery": str(attempt),
    }


def post_signed(callback_url: str, secret: str, event_ref: str, event_type: str,
                payload: dict, attempt: int = 1) -> tuple[int | None, str | None]:
    """
    POST the signed payload. Returns (http_status, error):
      - (2xx, None)        delivered
      - (status, None)     endpoint responded with a non-2xx status
      - (None, error str)  transport-level failure (DNS, TLS, timeout, ...)

    Never raises on delivery failure — a dead customer endpoint is a
    normal operating condition, not an exception (spec §9, retry storms).
    """
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = build_headers(event_ref, event_type, secret, body, attempt=attempt)
    try:
        resp = httpx.post(
            callback_url,
            content=body,
            headers=headers,
            timeout=DELIVERY_TIMEOUT_SECONDS,
            follow_redirects=False,  # redirects on a signed POST are a misconfiguration
        )
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:500]
    return resp.status_code, None


def test_event_payload(watch_ref: str, event_ref: str) -> dict:
    """The POST /{id}/test payload — proves signing + reachability end to end."""
    return {
        "id": event_ref,
        "type": "norric.test",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "watch_id": watch_ref,
        "data": {"message": "Norric Watch test event — signing and delivery OK"},
        "metadata": {
            "source": ["norric_watch"],
            "confidence": 1.0,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "signals": [],
        "warnings": [],
    }
