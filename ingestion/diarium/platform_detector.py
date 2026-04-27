"""
Detects which DMS platform a municipality uses.
Cache is per-run only (reset on process restart).
"""
import logging
from typing import Literal

import httpx

log = logging.getLogger(__name__)

Platform = Literal["platina", "evolution", "lex", "ephorte", "custom", "unknown"]

# In-memory per-run cache
_cache: dict[str, Platform] = {}

# Fingerprint: (URL suffix to try, string to look for in response)
_FINGERPRINTS: list[tuple[str, str, Platform]] = [
    ("/platina/", "platina",   "platina"),
    ("/evolution/", "Evolution", "evolution"),
    ("/lex/",      "Lex Diarium", "lex"),
    ("/ephorte/",  "ePhorte",  "ephorte"),
    ("",           "Platina",  "platina"),
    ("",           "evolution", "evolution"),
    ("",           "Ephorte",  "ephorte"),
]


async def detect_platform(
    municipality_url: str,
    session: httpx.AsyncClient,
) -> Platform:
    if municipality_url in _cache:
        return _cache[municipality_url]

    for suffix, marker, platform in _FINGERPRINTS:
        url = municipality_url.rstrip("/") + suffix
        try:
            resp = await session.get(url, timeout=10, follow_redirects=True)
            if marker.lower() in resp.text.lower():
                log.info("detected %s at %s", platform, municipality_url)
                _cache[municipality_url] = platform
                return platform
        except Exception:
            continue

    log.warning("could not detect platform for %s", municipality_url)
    _cache[municipality_url] = "unknown"
    return "unknown"
