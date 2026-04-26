"""
Tier policy — which tools are accessible per tier.

free       : status and explain tools only, max 100 calls/day
standard   : all tools, max 10_000 calls/day
compliance : all tools, unlimited, includes audit log access
"""
from collections import defaultdict
from datetime import date
from typing import Optional

FREE_TOOLS = {
    "norric_status_v1",
    "norric_explain_score_v1",
    "norric_data_freshness_v1",
}

RATE_LIMITS: dict[str, Optional[int]] = {
    "free":       100,
    "standard":   10_000,
    "compliance": None,      # unlimited
}

# In-memory call counter: {key_hash: {date_str: count}}
# Resets implicitly when date changes. Not persistent across restarts.
_counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def tool_allowed(tool_name: str, tier: str) -> bool:
    if tier in ("standard", "compliance"):
        return True
    if tier == "free":
        return tool_name in FREE_TOOLS
    return False


def rate_limit_for(tier: str) -> Optional[int]:
    return RATE_LIMITS.get(tier)


def check_and_increment(key_hash: str, tier: str) -> bool:
    """
    Returns True if the call is within rate limits and increments the counter.
    Returns False if the daily limit is exceeded.
    Compliance tier always returns True (unlimited).
    """
    limit = rate_limit_for(tier)
    if limit is None:
        return True

    today = date.today().isoformat()
    current = _counters[key_hash][today]
    if current >= limit:
        return False

    _counters[key_hash][today] += 1
    return True
