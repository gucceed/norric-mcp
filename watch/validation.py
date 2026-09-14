"""
watch/validation.py — event types, filters, tier limits, callback URLs.

The honesty rule lives here: EVENT_TYPES_V1 is exactly the set whose
pipelines are live today (Kreditvakt score diff + debt-signal ingestion).
Types whose pipelines are specified but not live are rejected with the
blocker named, so an API answer is never a promise the data can't keep.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

# ── Event types ──────────────────────────────────────────────────────────────

# v1 — buildable now: all four ride the live Kreditvakt beats.
EVENT_TYPES_V1 = frozenset({
    "company.risk_tier_changed",
    "company.score_changed",
    "company.debt_signal_new",
    "company.bankruptcy_status_changed",
})

# Specified but blocked — pipeline not live. Rejected with the blocker named.
EVENT_TYPES_BLOCKED = {
    "company.annual_report_filed": "annual-report ingestion pipeline is not live yet",
    "municipality.tender_posted": "SIGNAL ingestion is inactive",
}

# Live pipeline, Phase 2 scope (Sigvik BRF score API) — not in Phase 1.
EVENT_TYPES_PHASE2 = frozenset({"brf.score_changed"})

# ── Tier policy ──────────────────────────────────────────────────────────────

# Watch requires a paid tier. Free stays norric_status_v1-only.
WATCH_TIERS = frozenset({"standard", "compliance", "internal", "all"})

# Max watched entities across all of a key's watches (spec §4.1).
TIER_ENTITY_LIMITS = {
    "standard": 500,
    "compliance": 10_000,
    "internal": 10_000,
    "all": 10_000,
}

DEFAULT_MIN_SCORE_DELTA = 3
MAX_MIN_SCORE_DELTA = 20  # risk_score is 0–20

_ORGNR_RE = re.compile(r"^\d{10}$")


def tier_allows_watch(tier: str) -> bool:
    return tier in WATCH_TIERS


def tier_entity_limit(tier: str) -> int:
    return TIER_ENTITY_LIMITS.get(tier, 0)


def validate_event_types(event_types) -> list[str]:
    """
    Normalise + validate the requested event types.
    Returns a deduplicated list in request order.
    Raises ValueError on unknown types, and on blocked types with the
    blocker named — never a silent drop.
    """
    if not isinstance(event_types, (list, tuple)) or not event_types:
        raise ValueError("event_types must be a non-empty list")

    seen: list[str] = []
    for et in event_types:
        if not isinstance(et, str):
            raise ValueError(f"event type must be a string, got {type(et).__name__}")
        et = et.strip()
        if et in EVENT_TYPES_V1:
            if et not in seen:
                seen.append(et)
        elif et in EVENT_TYPES_BLOCKED:
            raise ValueError(
                f"event type {et!r} is specified but not available: "
                f"{EVENT_TYPES_BLOCKED[et]}"
            )
        elif et in EVENT_TYPES_PHASE2:
            raise ValueError(
                f"event type {et!r} ships in Phase 2 (batched/BRF delivery), "
                "not available yet"
            )
        else:
            raise ValueError(
                f"unknown event type {et!r}. Valid: {', '.join(sorted(EVENT_TYPES_V1))}"
            )
    return seen


def normalize_orgnr(v: str) -> str:
    """Dashless 10-digit orgnr — the canonical key form used by norric tables."""
    clean = str(v).replace("-", "").replace(" ", "")
    if not _ORGNR_RE.fullmatch(clean) or clean[0] == "0":
        raise ValueError(f"Invalid Swedish organisation number: {v!r}. Example: 556000-1234")
    return clean


def validate_filters(filters) -> dict:
    """
    Normalise the v1 filter shape:
        {"orgnrs": [...], "min_score_delta": int}

    Filters compose within a watch: an entity matches when it appears in
    orgnrs (the only v1 entity filter); min_score_delta gates
    company.score_changed. Unknown keys are rejected so typos don't
    silently widen a watch to everything.
    """
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")

    allowed = {"orgnrs", "min_score_delta"}
    unknown = set(filters) - allowed
    if unknown:
        raise ValueError(
            f"unknown filter keys: {', '.join(sorted(unknown))}. "
            f"Valid: {', '.join(sorted(allowed))}"
        )

    out: dict = {}

    orgnrs = filters.get("orgnrs") or []
    if not isinstance(orgnrs, list):
        raise ValueError("filters.orgnrs must be a list")
    norm: list[str] = []
    for o in orgnrs:
        n = normalize_orgnr(o)
        if n not in norm:
            norm.append(n)
    out["orgnrs"] = norm

    delta = filters.get("min_score_delta", DEFAULT_MIN_SCORE_DELTA)
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise ValueError("filters.min_score_delta must be an integer")
    if not 1 <= delta <= MAX_MIN_SCORE_DELTA:
        raise ValueError(
            f"filters.min_score_delta must be 1–{MAX_MIN_SCORE_DELTA}, got {delta}"
        )
    out["min_score_delta"] = delta

    return out


def entity_count(filters: dict) -> int:
    """Watched-entity count for tier-limit accounting (v1: orgnrs only)."""
    return len(filters.get("orgnrs") or [])


# ── Callback URL validation + SSRF guard ─────────────────────────────────────

def _ip_blocked(ip: ipaddress._BaseAddress) -> bool:  # type: ignore[name-defined]
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp")


def validate_callback_url(url: str, resolve_dns: bool = False) -> str:
    """
    Validate a customer callback URL.

    Rules (spec §6 — security is table stakes for platform security teams):
      - HTTPS only. No plaintext HTTP callbacks, ever.
      - No userinfo, no fragments.
      - Hostname must not be a loopback/private alias.
      - IP-literal hosts in private/reserved ranges are rejected.
      - With resolve_dns=True (API layer at creation time), the hostname is
        resolved and every returned address is checked — blocks a public
        name pointing at 10.0.0.x. resolve_dns=False keeps validation
        hermetic for unit tests and offline worker contexts.

    Returns the URL unchanged on success; raises ValueError otherwise.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("callback_url is required")
    url = url.strip()
    if len(url) > 2048:
        raise ValueError("callback_url too long (max 2048 chars)")

    try:
        parts = urlsplit(url)
    except ValueError as e:
        raise ValueError(f"invalid callback_url: {e}") from e

    if parts.scheme.lower() != "https":
        raise ValueError("callback_url must use https://")
    if not parts.hostname:
        raise ValueError("callback_url must include a hostname")
    if parts.username or parts.password:
        raise ValueError("callback_url must not contain credentials")
    if parts.fragment:
        raise ValueError("callback_url must not contain a fragment")
    try:
        _ = parts.port  # raises on malformed port
    except ValueError as e:
        raise ValueError(f"invalid callback_url port: {e}") from e

    host = parts.hostname.lower().rstrip(".")

    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise ValueError(f"callback_url host {host!r} is not allowed")

    # IP-literal host → check the range directly
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if _ip_blocked(ip):
            raise ValueError(f"callback_url must not target a private or reserved address ({host})")
        return url

    if resolve_dns:
        import socket

        try:
            infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise ValueError(f"callback_url hostname does not resolve: {host}") from e
        addrs = {info[4][0] for info in infos}
        if not addrs:
            raise ValueError(f"callback_url hostname does not resolve: {host}")
        for addr in addrs:
            if _ip_blocked(ipaddress.ip_address(addr)):
                raise ValueError(
                    f"callback_url host {host!r} resolves to a private or reserved address"
                )

    return url
