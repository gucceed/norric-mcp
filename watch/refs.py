"""
watch/refs.py — public identifier generation.

watch_ref / event_ref are the customer-facing IDs (watch_…, evt_…).
The signing secret is shown once at creation (whsec_…) and stored
server-side for HMAC-SHA256 payload signing.
"""
import secrets


def new_watch_ref() -> str:
    return f"watch_{secrets.token_hex(8)}"


def new_event_ref() -> str:
    return f"evt_{secrets.token_hex(8)}"


def new_signing_secret() -> str:
    return f"whsec_{secrets.token_hex(24)}"
