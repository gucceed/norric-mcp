"""
Norric key generation utilities.
"""
import hashlib
import secrets


def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, hash). Send raw_key to customer. Store hash."""
    raw = "nrc_" + secrets.token_urlsafe(32)
    h = hashlib.sha256(raw.encode()).hexdigest()
    return raw, h


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def format_key_line(raw_key: str, tier: str, label: str) -> str:
    """Format one line for NORRIC_API_KEYS env var."""
    h = hash_key(raw_key)
    return f"{h}:{tier}:{label}"
