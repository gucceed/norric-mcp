"""
Tier policy — which tools are accessible per tier and per-minute rate limits.

free       : norric_status_v1 only, 50 calls/month (DB), 5 calls/minute (in-memory)
standard   : all tools, no call cap
compliance : all tools, no call cap, includes audit log access
"""
import time
from collections import defaultdict, deque
from typing import Optional

FREE_TOOLS = {
    "norric_status_v1",
}

FREE_RATE_PER_MIN = 5

# Sliding-window per-minute tracker: {key_hash: deque of monotonic timestamps}
_rate_window: dict[str, deque] = defaultdict(deque)


def tool_allowed(tool_name: str, tier: str) -> bool:
    if tier in ("standard", "compliance"):
        return True
    if tier == "free":
        return tool_name in FREE_TOOLS
    return False


def check_rate_limit(key_hash: str) -> bool:
    """
    Returns True if the key is within 5 calls/minute, and records the call.
    Returns False if the limit is exceeded (do not record).
    Only applies to Free tier — caller is responsible for gating by tier.
    """
    now = time.monotonic()
    window = _rate_window[key_hash]
    while window and now - window[0] > 60.0:
        window.popleft()
    if len(window) >= FREE_RATE_PER_MIN:
        return False
    window.append(now)
    return True
