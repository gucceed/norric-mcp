"""
Kreditvakt error taxonomy (3.1).

Each code has: HTTP status, customer-facing message, log severity, retryable flag.
All user-visible strings are in Swedish. Internal codes are English.
"""
from __future__ import annotations
from enum import Enum


class ErrCode(str, Enum):
    # 4xx — client fault
    VALIDATION_FAILED    = "VALIDATION_FAILED"    # 400 bad orgnr
    AUTH_REQUIRED        = "AUTH_REQUIRED"         # 401 missing/invalid key
    SEARCH_LIMIT_REACHED = "SEARCH_LIMIT_REACHED"  # 402 free tier cap
    TIER_INSUFFICIENT    = "TIER_INSUFFICIENT"     # 403 feature locked

    # 5xx — server fault
    UPSTREAM_TIMEOUT     = "UPSTREAM_TIMEOUT"      # 504 DB/scoring timed out
    UPSTREAM_RATE_LIMIT  = "UPSTREAM_RATE_LIMIT"   # 429 upstream throttled
    UPSTREAM_DEGRADED    = "UPSTREAM_DEGRADED"     # 503 circuit open
    SCHEMA_MISSING       = "SCHEMA_MISSING"        # 500 DB table absent
    CONFIG_MISSING       = "CONFIG_MISSING"        # 500 env var absent
    SCORING_ERROR        = "SCORING_ERROR"         # 500 unexpected


_HTTP: dict[ErrCode, int] = {
    ErrCode.VALIDATION_FAILED:    400,
    ErrCode.AUTH_REQUIRED:        401,
    ErrCode.SEARCH_LIMIT_REACHED: 402,
    ErrCode.TIER_INSUFFICIENT:    403,
    ErrCode.UPSTREAM_TIMEOUT:     504,
    ErrCode.UPSTREAM_RATE_LIMIT:  429,
    ErrCode.UPSTREAM_DEGRADED:    503,
    ErrCode.SCHEMA_MISSING:       500,
    ErrCode.CONFIG_MISSING:       500,
    ErrCode.SCORING_ERROR:        500,
}

_MSG: dict[ErrCode, str] = {
    ErrCode.VALIDATION_FAILED:
        "Ogiltigt organisationsnummer — ange 10 siffror (t.ex. 556123-4567).",
    ErrCode.AUTH_REQUIRED:
        "Ogiltig API-nyckel. Skaffa en ny på kreditvakt.com/signup.",
    ErrCode.SEARCH_LIMIT_REACHED:
        "Du har använt dina 10 gratis sökningar. Uppgradera till Silver för obegränsade sökningar.",
    ErrCode.TIER_INSUFFICIENT:
        "Den här funktionen kräver Silver-abonnemang eller högre.",
    ErrCode.UPSTREAM_TIMEOUT:
        "Sökmotorn svarade inte i tid — försök igen om 30 sekunder.",
    ErrCode.UPSTREAM_RATE_LIMIT:
        "För många förfrågningar. Free-tier: 10 sökningar/minut. Vänta en minut och försök igen.",
    ErrCode.UPSTREAM_DEGRADED:
        "Sökmotorn är tillfälligt degraderad. Uppskattad återhämtning: 30 sekunder.",
    ErrCode.SCHEMA_MISSING:
        "Databasschemat är ofullständigt — kontakta hej@norric.io.",
    ErrCode.CONFIG_MISSING:
        "Tjänstekonfigurationsfel — kontakta hej@norric.io.",
    ErrCode.SCORING_ERROR:
        "Ett oväntat fel uppstod. Försök igen om en stund eller kontakta hej@norric.io.",
}

_SEVERITY: dict[ErrCode, str] = {
    ErrCode.VALIDATION_FAILED:    "info",
    ErrCode.AUTH_REQUIRED:        "info",
    ErrCode.SEARCH_LIMIT_REACHED: "info",
    ErrCode.TIER_INSUFFICIENT:    "info",
    ErrCode.UPSTREAM_TIMEOUT:     "warning",
    ErrCode.UPSTREAM_RATE_LIMIT:  "warning",
    ErrCode.UPSTREAM_DEGRADED:    "warning",
    ErrCode.SCHEMA_MISSING:       "critical",
    ErrCode.CONFIG_MISSING:       "critical",
    ErrCode.SCORING_ERROR:        "error",
}

_RETRYABLE: dict[ErrCode, bool] = {
    ErrCode.VALIDATION_FAILED:    False,
    ErrCode.AUTH_REQUIRED:        False,
    ErrCode.SEARCH_LIMIT_REACHED: False,
    ErrCode.TIER_INSUFFICIENT:    False,
    ErrCode.UPSTREAM_TIMEOUT:     True,
    ErrCode.UPSTREAM_RATE_LIMIT:  True,
    ErrCode.UPSTREAM_DEGRADED:    True,
    ErrCode.SCHEMA_MISSING:       False,
    ErrCode.CONFIG_MISSING:       False,
    ErrCode.SCORING_ERROR:        True,
}


def http_status(code: ErrCode) -> int:
    return _HTTP[code]

def customer_message(code: ErrCode) -> str:
    return _MSG[code]

def log_severity(code: ErrCode) -> str:
    return _SEVERITY[code]

def is_retryable(code: ErrCode) -> bool:
    return _RETRYABLE[code]
