"""
Norric MCP — API key validation layer.

Keys are stored as SHA-256 hashes in the environment variable NORRIC_API_KEYS,
formatted as a newline-separated list of:
  {sha256_hash}:{tier}:{label}

Example env value:
  abc123...:{tier}:norion_bank_pilot
  def456...:{tier}:serafim_finans_pilot

Tiers: free | standard | compliance
"""
import hashlib
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ApiKey:
    hash: str
    tier: str        # free | standard | compliance
    label: str       # human-readable identifier, never returned to caller


def _load_keys() -> dict[str, ApiKey]:
    raw = os.environ.get("NORRIC_API_KEYS", "")
    keys: dict[str, ApiKey] = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        h, tier, label = parts
        keys[h] = ApiKey(hash=h, tier=tier, label=label)
    return keys


_KEYS: dict[str, ApiKey] = _load_keys()


def validate_key(raw_key: str) -> Optional[ApiKey]:
    """Return ApiKey if valid, None if not."""
    h = hashlib.sha256(raw_key.encode()).hexdigest()
    return _KEYS.get(h)


def reload_keys() -> None:
    """Call after rotating NORRIC_API_KEYS env var without restart."""
    global _KEYS
    _KEYS = _load_keys()


def generate_key_hash(raw_key: str) -> str:
    """Utility — hash a raw key for insertion into NORRIC_API_KEYS."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
