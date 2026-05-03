"""
Norric MCP — API key validation layer.

Keys are stored in the api_keys table (T2_009). Every request validates against
the DB so keys issued via Stripe are immediately valid without a redeploy.

Tiers: free | standard | compliance
"""
import hashlib
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ApiKey:
    hash: str
    tier: str           # free | standard | compliance
    label: str          # email address — never returned to caller
    org_nr: str | None  # 10-digit org number — used for org-level quota


def validate_key(raw_key: str) -> Optional[ApiKey]:
    """
    Hash the raw key and look it up in api_keys where status=active.
    Returns ApiKey on match, None otherwise.
    Synchronous — call via asyncio.to_thread() from async contexts.
    """
    from ingestion.db import Session
    from sqlalchemy import text

    h = hashlib.sha256(raw_key.encode()).hexdigest()
    db = Session()
    try:
        row = db.execute(
            text("SELECT key_hash, tier, email, org_nr FROM api_keys WHERE key_hash = :h AND status = 'active'"),
            {"h": h},
        ).fetchone()
        if row is None:
            return None
        return ApiKey(hash=row.key_hash, tier=row.tier, label=row.email, org_nr=row.org_nr)
    finally:
        db.close()


def generate_key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
