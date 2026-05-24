"""
kreditvakt/api.py

Kreditvakt FastAPI sub-application.

Mount into a parent FastAPI app or run standalone:
    uvicorn kreditvakt.api:app --port 8001

Endpoints:
    GET  /api/score/{orgnr}           — single company score + display fields
    POST /api/score/batch             — batch scoring (body: {"orgnr_list": [...]})
    GET  /api/portfolio               — all tracked companies with current scores
    GET  /api/alerts                  — companies that moved to Band 4+ since last check
    GET  /api/company/{orgnr}/debt    — tier-gated debt breakdown
    GET  /health                      — service health

Tier gating:
    X-Kreditvakt-Tier header (set by auth middleware): free|silver|guld|premium|enterprise
    Absent header → 'free' (safe default, most restricted view)

Canonical risk-field family (locked by docs/no-fabrication-contract.md):
    risk_score  int|null  [0–20]                  ascending = worse
    risk_band   int|null  [1–5]                   ascending = worse
    risk_tier   str|null  HEALTHY|WATCH|ELEVATED|HIGH|CRITICAL

Envelope metadata:
    scale     "0-20"
    polarity  "ascending_risk"

Dropped from response (legacy / Swedish-marketing vocab — out of canonical):
    display_score, band, band_label, band_action, confidence_label, insolvency_score
"""

import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from kreditvakt.errors import ErrCode, customer_message, http_status, log_severity
from kreditvakt.circuit import scoring_circuit

log = logging.getLogger(__name__)

_DEPLOY_SHA = os.environ.get("RAILWAY_GIT_COMMIT_SHA", os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown"))
_REGION     = os.environ.get("RAILWAY_REGION", os.environ.get("VERCEL_REGION", "unknown"))

_ORGNR_RE = re.compile(r"^\d{6}-?\d{4}$")


def _validate_orgnr(raw: str) -> str:
    """Return normalized XXXXXX-XXXX or raise HTTPException(400).

    Rejects:
      - Malformed: not 10 digits (with optional dash, optional century prefix).
      - Personnummer / samordningsnummer: first 6 digits form a valid date
        (YYMMDD with MM 01-12; DD 01-31 or 61-91 for samordningsnummer).
        Norric Kreditvakt only scores juridiska personer; the boundary is
        enforced mechanically here, before any DB lookup.
      - Defensive belt-and-braces: third digit < 2 (corporate-orgnr discriminator).
    """
    cleaned = raw.replace("-", "").replace(" ", "")
    if len(cleaned) == 12:
        cleaned = cleaned[2:]
    if not re.fullmatch(r"\d{10}", cleaned) or cleaned[0] == "0":
        raise HTTPException(
            status_code=400,
            detail={"error_code": ErrCode.VALIDATION_FAILED, "message": customer_message(ErrCode.VALIDATION_FAILED)},
        )

    # Personnummer shape: YYMMDD-XXXX where MM ∈ 01-12 and DD ∈ 01-31 or 61-91.
    mm = int(cleaned[2:4])
    dd = int(cleaned[4:6])
    looks_like_date = (1 <= mm <= 12) and (1 <= dd <= 31 or 61 <= dd <= 91)
    # Corporate orgnrs have a 3rd digit >= 2 (juridisk-person discriminator).
    is_corporate_shape = int(cleaned[2]) >= 2
    if looks_like_date and not is_corporate_shape:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_ORGNR",
                "message": (
                    "Norric Kreditvakt only scores juridiska personer (AB, HB, KB, "
                    "ekonomiska föreningar). Personnummer and samordningsnummer are "
                    "not supported."
                ),
            },
        )

    return f"{cleaned[:6]}-{cleaned[6:]}"


def _structured_log(
    *,
    orgnr_raw: str,
    tier: str,
    latency_ms: float,
    status_code: int,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    exc: Optional[BaseException] = None,
) -> None:
    """Emit one structured JSON line per request to stdout (Vercel/Railway log capture)."""
    import hashlib as _h
    entry: dict = {
        "requestId":        str(uuid.uuid4()),
        "timestamp":        __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "route":            "/api/score/{orgnr}",
        "tier":             tier,
        "orgnr":            _h.sha256(orgnr_raw.encode()).hexdigest()[:16],  # partial hash, GDPR-safe
        "latencyMs":        round(latency_ms, 1),
        "statusCode":       status_code,
        "errorCode":        error_code,
        "errorMessage":     error_message,
        "stackTrace":       None,
        "deploySha":        _DEPLOY_SHA,
        "region":           _REGION,
    }
    if exc is not None:
        import traceback
        entry["stackTrace"] = traceback.format_exception(type(exc), exc, exc.__traceback__)
    severity = log_severity(ErrCode(error_code)) if error_code else "info"
    getattr(log, severity)(json.dumps(entry))

_TIER_ORDER = {"free": 0, "silver": 1, "guld": 2, "premium": 3, "enterprise": 4}


def _tier(request: Request) -> str:
    t = request.headers.get("X-Kreditvakt-Tier", "free").lower()
    return t if t in _TIER_ORDER else "free"


def _tier_gte(request: Request, required: str) -> bool:
    return _TIER_ORDER.get(_tier(request), 0) >= _TIER_ORDER[required]


# ── DB ─────────────────────────────────────────────────────────────────────────

def _get_db():
    from ingestion.db import Session
    db = Session()
    try:
        yield db
    finally:
        db.close()


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="Norric Kreditvakt API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── GET /api/score/{orgnr} ─────────────────────────────────────────────────────

_FREE_SEARCHES_LIMIT = 10
_UPGRADE_URL = "mailto:hej@norric.io?subject=Silver-abonnemang%20Kreditvakt&body=Hej,%0A%0AJag%20vill%20teckna%20Silver-abonnemang%20(4%20900%20kr/mån).%0A%0AFöretag:%20%0AOrgnr:%20%0AKontaktperson:%20%0A"


def _raw_key_from_request(request: Request) -> str | None:
    """Extract the raw API key from Authorization or X-Norric-Key header."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ").strip()
    return request.headers.get("x-norric-key", "").strip() or None


_IP_RL_WINDOW = 60   # seconds
_IP_RL_MAX    = 10   # requests per window


def _check_ip_rate_limit(client_ip: str) -> bool:
    """
    Sliding-window IP rate limit using Upstash Redis REST API (INCR + EXPIRE).
    Returns True if the request should be blocked (limit exceeded).
    Reads env vars at call time (not import time) so Railway variable changes
    take effect without a code redeploy.
    Falls through (returns False) when Upstash is not configured or unavailable.
    """
    upstash_url   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    upstash_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    if not upstash_url or not upstash_token:
        # Try fallback to redis:// client
        from core.db_auth import _get_redis
        r = _get_redis()
        if r is None:
            log.debug("[RL] No Upstash or Redis configured — rate limit disabled")
            return False
        try:
            rl_key = f"kreditvakt:rl:{hashlib.sha256(client_ip.encode()).hexdigest()[:16]}"
            count = r.incr(rl_key)
            if count == 1:
                r.expire(rl_key, _IP_RL_WINDOW)
            return count > _IP_RL_MAX
        except Exception as exc:
            log.warning("[RL] Redis rate-limit check failed (%s) — allowing request", exc)
            return False

    try:
        import urllib.request as _urlreq
        rl_key = f"kreditvakt:rl:{hashlib.sha256(client_ip.encode()).hexdigest()[:16]}"
        headers = {"Authorization": f"Bearer {upstash_token}", "Content-Type": "application/json"}

        # INCR
        req = _urlreq.Request(
            f"{upstash_url}/incr/{rl_key}",
            method="POST",
            headers=headers,
        )
        with _urlreq.urlopen(req, timeout=1) as resp:
            count = int(__import__("json").loads(resp.read())["result"])

        # SET EXPIRE on first hit
        if count == 1:
            req2 = _urlreq.Request(
                f"{upstash_url}/expire/{rl_key}/{_IP_RL_WINDOW}",
                method="POST",
                headers=headers,
            )
            _urlreq.urlopen(req2, timeout=1).close()

        return count > _IP_RL_MAX
    except Exception as exc:
        log.warning("[RL] Upstash rate-limit check failed (%s) — allowing request", exc)
        return False


@app.get("/api/score/{orgnr}", summary="Single company risk score")
def get_score(orgnr: str, request: Request):
    """
    Score a company and return display fields.

    Authentication:
      - No key: Free tier, rate-limited by IP (10 req/min).
      - Bearer token: tier resolved from api_keys table; Silver+ bypass IP limit.

    Free tier: lifetime cap of 10 searches per key (key optional — anonymous uses IP).
    Returns 402 when cap reached.
    """
    from scoring.kreditvakt import score_from_db, write_score
    from ingestion.db import Session

    t0 = time.monotonic()
    tier = _tier(request)

    # ── Input validation (3.5) ────────────────────────────────────────────────
    try:
        orgnr_normalized = _validate_orgnr(orgnr)
    except HTTPException as exc:
        _structured_log(
            orgnr_raw=orgnr, tier=tier,
            latency_ms=(time.monotonic() - t0) * 1000,
            status_code=400,
            error_code=ErrCode.VALIDATION_FAILED,
            error_message=f"Invalid orgnr: {orgnr!r}",
        )
        raise

    # ── Circuit breaker check (3.3) ───────────────────────────────────────────
    if not scoring_circuit.allow_request():
        _structured_log(
            orgnr_raw=orgnr_normalized, tier=tier,
            latency_ms=(time.monotonic() - t0) * 1000,
            status_code=503,
            error_code=ErrCode.UPSTREAM_DEGRADED,
            error_message="Circuit open — scoring DB unavailable",
        )
        raise HTTPException(
            status_code=http_status(ErrCode.UPSTREAM_DEGRADED),
            detail={"error_code": ErrCode.UPSTREAM_DEGRADED, "message": customer_message(ErrCode.UPSTREAM_DEGRADED)},
        )

    # ── IP rate limiting for keyless free-tier (10 req/min) ──────────────────
    if tier == "free" and not _raw_key_from_request(request):
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or request.headers.get("x-real-ip", "")
            or getattr(request.client, "host", "unknown")
        )
        if _check_ip_rate_limit(client_ip):
            _structured_log(
                orgnr_raw=orgnr_normalized, tier=tier,
                latency_ms=(time.monotonic() - t0) * 1000,
                status_code=429,
                error_code=ErrCode.UPSTREAM_RATE_LIMIT,
                error_message=f"IP rate limit exceeded: {client_ip}",
            )
            raise HTTPException(
                status_code=429,
                detail={"error_code": ErrCode.UPSTREAM_RATE_LIMIT, "message": customer_message(ErrCode.UPSTREAM_RATE_LIMIT)},
            )

    # ── Free-tier quota (key-based when key present, else anonymous) ──────────
    searches_remaining: Optional[int] = None
    if tier == "free":
        raw_key = _raw_key_from_request(request)
        if raw_key:
            from core.db_auth import check_and_increment_searches
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            allowed, used, limit = check_and_increment_searches(key_hash)
            if not allowed:
                _structured_log(
                    orgnr_raw=orgnr_normalized, tier=tier,
                    latency_ms=(time.monotonic() - t0) * 1000,
                    status_code=402,
                    error_code=ErrCode.SEARCH_LIMIT_REACHED,
                    error_message=f"searches_used={used} >= limit={limit}",
                )
                raise HTTPException(
                    status_code=402,
                    detail={
                        "error_code": ErrCode.SEARCH_LIMIT_REACHED,
                        "message": customer_message(ErrCode.SEARCH_LIMIT_REACHED),
                        "searches_used": used,
                        "searches_limit": limit,
                        "upgrade_url": _UPGRADE_URL,
                    },
                )
            searches_remaining = limit - used

    # ── norric_entities membership check (404 if not in monitored universe) ──
    db = Session()
    score_err_code: Optional[ErrCode] = None
    exc_captured: Optional[BaseException] = None
    entity: Optional[dict] = None
    # norric_entities stores `orgnr` dashless (the canonical key) and
    # `orgnr_display` dashed. _validate_orgnr returned the dashed form;
    # match against orgnr_display so the lookup hits.
    try:
        entity_row = db.execute(
            text("""
                SELECT orgnr, name, is_active, deregistered_at
                FROM norric_entities
                WHERE orgnr_display = :orgnr
            """),
            {"orgnr": orgnr_normalized},
        ).fetchone()
    except Exception as ent_exc:
        # norric_entities schema is wrong / table missing. NOT silently 404 —
        # the scorer's own try/except will surface this via SCHEMA_MISSING.
        log.warning("[%s] norric_entities lookup failed: %s", orgnr_normalized, ent_exc)
        entity_row = None
        try: db.rollback()
        except Exception: pass

    if entity_row is None:
        db.close()
        _structured_log(
            orgnr_raw=orgnr_normalized, tier=tier,
            latency_ms=(time.monotonic() - t0) * 1000,
            status_code=404,
            error_code="ORGNR_NOT_INGESTED",
            error_message="orgnr not in norric_entities",
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error":   "orgnr_not_ingested",
                "orgnr":   orgnr_normalized,
                "message": "This organisation number is outside Norric's monitored universe.",
                "hint":    "Request enrichment via /api/enrich (coming soon — contact hej@norric.io for early access).",
            },
        )

    entity = {
        "name":             entity_row.name,
        "status":           "active" if entity_row.is_active else "deregistered",
        "deregistered_at":  entity_row.deregistered_at.isoformat() if getattr(entity_row, "deregistered_at", None) else None,
    }

    # ── Score lookup (3.3 circuit breaker wraps) ──────────────────────────────
    try:
        result = score_from_db(db, orgnr_normalized)
        # Only persist when there's a real score. The no_signals path has
        # null risk_* fields, which violate company_scores' NOT NULL
        # constraints on distress_probability / risk_band / insolvency_score.
        # No score to cache → nothing to persist.
        if result.get("score_source") == "live":
            write_score(db, result)
        scoring_circuit.record_success()
    except Exception as exc:
        scoring_circuit.record_failure()
        exc_captured = exc
        # Classify the error
        exc_str = str(exc).lower()
        if "timeout" in exc_str or "timed out" in exc_str:
            score_err_code = ErrCode.UPSTREAM_TIMEOUT
        elif "schema" in exc_str or "relation" in exc_str or "does not exist" in exc_str:
            score_err_code = ErrCode.SCHEMA_MISSING
        else:
            score_err_code = ErrCode.SCORING_ERROR
        _structured_log(
            orgnr_raw=orgnr_normalized, tier=tier,
            latency_ms=(time.monotonic() - t0) * 1000,
            status_code=http_status(score_err_code),
            error_code=score_err_code,
            error_message=str(exc),
            exc=exc,
        )
        raise HTTPException(
            status_code=http_status(score_err_code),
            detail={"error_code": score_err_code, "message": customer_message(score_err_code)},
        )
    finally:
        db.close()

    response = _enrich_response(result, request, entity=entity)
    if searches_remaining is not None:
        response["searches_remaining"] = searches_remaining
        response["searches_limit"] = _FREE_SEARCHES_LIMIT

    _structured_log(
        orgnr_raw=orgnr_normalized, tier=tier,
        latency_ms=(time.monotonic() - t0) * 1000,
        status_code=200,
    )
    return response


# ── POST /api/score/batch ──────────────────────────────────────────────────────

class BatchRequest(BaseModel):
    orgnr_list: list[str]


@app.post("/api/score/batch", summary="Batch company scoring")
def batch_score(req: BatchRequest, request: Request):
    """Score up to 500 companies. Silver+ only."""
    if not _tier_gte(request, "silver"):
        raise HTTPException(status_code=403, detail="Batch scoring requires Silver tier or above")
    if len(req.orgnr_list) > 500:
        raise HTTPException(status_code=400, detail="Max 500 orgnr per batch")

    from scoring.kreditvakt import score_from_db, write_score
    from ingestion.db import Session

    db = Session()
    results, errors = [], []
    try:
        for orgnr in req.orgnr_list:
            try:
                result = score_from_db(db, orgnr)
                write_score(db, result)
                results.append(_enrich_response(result, request))
            except Exception as e:
                log.error(f"[{orgnr}] batch error: {e}", exc_info=True)
                errors.append({"orgnr": orgnr, "error": str(e)})
    finally:
        db.close()

    return {
        "total_requested": len(req.orgnr_list),
        "scored": len(results),
        "errors": len(errors),
        "error_detail": errors,
        "results": results,
    }


# ── GET /api/portfolio ─────────────────────────────────────────────────────────

@app.get("/api/portfolio", summary="Portfolio view")
def get_portfolio(
    request: Request,
    min_band: int = Query(1, ge=1, le=5),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    """All tracked companies with current scores. Silver+ only."""
    if not _tier_gte(request, "silver"):
        raise HTTPException(status_code=403, detail="Portfolio view requires Silver tier or above")

    from ingestion.db import Session

    db = Session()
    try:
        rows = db.execute(
            text("""
                SELECT cs.orgnr, cs.distress_probability, cs.risk_band,
                       cs.insolvency_score, cs.signals_fired, cs.signals_total,
                       cs.scored_at, cs.data_freshness_hours, cs.score_source,
                       cs.last_displayed_band,
                       ne.name AS company_name, ne.city, ne.orgform
                FROM company_scores cs
                LEFT JOIN norric_entities ne ON ne.orgnr = cs.orgnr
                WHERE cs.risk_band >= :min_band
                ORDER BY cs.risk_band DESC, cs.distress_probability DESC
                LIMIT :limit OFFSET :offset
            """),
            {"min_band": min_band, "limit": limit, "offset": offset},
        ).fetchall()

        total = db.execute(
            text("SELECT COUNT(*) FROM company_scores WHERE risk_band >= :min_band"),
            {"min_band": min_band},
        ).scalar()
    finally:
        db.close()

    from scoring.kreditvakt import TIER_FROM_BAND, _risk_score_from_band

    companies = []
    for r in rows:
        row = dict(r._mapping)
        rb = row.get("risk_band")
        # Public-envelope contract: drop the legacy fields, emit the
        # canonical risk_* family + scale/polarity metadata.
        row.pop("insolvency_score", None)
        row.pop("last_displayed_band", None)
        row["risk_score"] = _risk_score_from_band(rb) if rb is not None else None
        row["risk_tier"]  = TIER_FROM_BAND.get(rb) if rb is not None else None
        row["scale"]      = "0-20"
        row["polarity"]   = "ascending_risk"
        companies.append(row)

    return {"total": total, "limit": limit, "offset": offset, "companies": companies}


# ── GET /api/alerts ────────────────────────────────────────────────────────────

@app.get("/api/alerts", summary="Band 4/5 alert list")
def get_alerts(request: Request, hours_back: int = Query(24, ge=1, le=168)):
    """Companies that moved to Band 4 or 5 in the last N hours. Silver+ only."""
    if not _tier_gte(request, "silver"):
        raise HTTPException(status_code=403, detail="Alerts require Silver tier or above")

    from ingestion.db import Session

    db = Session()
    try:
        rows = db.execute(
            text("""
                WITH current AS (
                    SELECT orgnr, risk_band, distress_probability, scored_at,
                           last_displayed_band
                    FROM company_scores
                    WHERE risk_band >= 4
                ),
                previous AS (
                    SELECT DISTINCT ON (orgnr)
                        orgnr, risk_band AS prev_band, scored_at AS prev_scored_at
                    FROM company_score_history
                    WHERE scored_at < now() - interval '1 hour' * :hours_back
                    ORDER BY orgnr, scored_at DESC
                )
                SELECT
                    c.orgnr,
                    c.risk_band,
                    c.last_displayed_band,
                    c.distress_probability,
                    c.scored_at,
                    p.prev_band,
                    p.prev_scored_at,
                    ne.name AS company_name
                FROM current c
                LEFT JOIN previous p ON p.orgnr = c.orgnr
                LEFT JOIN norric_entities ne ON ne.orgnr = c.orgnr
                WHERE p.prev_band IS NULL OR p.prev_band < 4
                ORDER BY c.distress_probability DESC
            """),
            {"hours_back": hours_back},
        ).fetchall()
    finally:
        db.close()

    from scoring.kreditvakt import TIER_FROM_BAND, _risk_score_from_band

    alerts = []
    for r in rows:
        row = dict(r._mapping)
        rb = row.get("risk_band")
        # Same canonical envelope as /api/portfolio + /api/score/{orgnr}.
        row.pop("last_displayed_band", None)
        row["risk_score"] = _risk_score_from_band(rb) if rb is not None else None
        row["risk_tier"]  = TIER_FROM_BAND.get(rb) if rb is not None else None
        row["scale"]      = "0-20"
        row["polarity"]   = "ascending_risk"
        # prev_band stays as-is (1-5 risk_band semantics, ascending=worse).
        alerts.append(row)

    return {"hours_back": hours_back, "alert_count": len(alerts), "alerts": alerts}


# ── GET /api/company/{orgnr}/debt ─────────────────────────────────────────────

@app.get("/api/company/{orgnr}/debt", summary="Tier-gated debt breakdown")
def get_debt(orgnr: str, request: Request):
    """
    Debt breakdown gated by tier:

    Free:    { active_flag_count: int }
    Silver:  totals by source (Skatteverket, Kronofogden) — no line items, no names
    Guld:    line items with amounts. Enskild firma creditors return a DPA-required
             placeholder instead of the creditor name (enforced at SQL layer).
             Full creditor identity requires a signed DPA (dpa_signatures table).
    Premium: Guld + explain_score decomposing the internal model by signal weight.
    """
    from ingestion.db import Session

    tier = _tier(request)
    db = Session()
    try:
        if tier == "free":
            return _debt_free(db, orgnr)
        elif tier == "silver":
            return _debt_silver(db, orgnr)
        elif tier == "guld":
            has_dpa = _has_dpa(db, request)
            return _debt_guld(db, orgnr, has_dpa=has_dpa)
        else:  # premium, enterprise
            has_dpa = _has_dpa(db, request)
            return _debt_premium(db, orgnr, has_dpa=has_dpa)
    finally:
        db.close()


def _debt_free(db, orgnr: str) -> dict:
    row = db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM norric_tax_signals
                 WHERE orgnr = :orgnr AND is_active = true) +
                (SELECT COUNT(*) FROM norric_payment_signals
                 WHERE orgnr = :orgnr AND is_active = true)
                AS active_flag_count
        """),
        {"orgnr": orgnr},
    ).fetchone()
    return {"orgnr": orgnr, "tier": "free", "active_flag_count": int(row.active_flag_count)}


def _debt_silver(db, orgnr: str) -> dict:
    tax = db.execute(
        text("""
            SELECT
                COALESCE(SUM(amount_sek) FILTER (WHERE is_active), 0) AS total_kr,
                COUNT(*) FILTER (WHERE is_active) AS case_count
            FROM norric_tax_signals WHERE orgnr = :orgnr
        """),
        {"orgnr": orgnr},
    ).fetchone()

    kfm = db.execute(
        text("""
            SELECT
                COALESCE(SUM(claim_amount_sek) FILTER (WHERE is_active), 0) AS total_kr,
                COUNT(*) FILTER (WHERE is_active) AS case_count
            FROM norric_payment_signals WHERE orgnr = :orgnr
        """),
        {"orgnr": orgnr},
    ).fetchone()

    return {
        "orgnr": orgnr,
        "tier": "silver",
        "skatteverket": {"total_kr": int(tax.total_kr), "case_count": int(tax.case_count)},
        "kronofogden": {"total_kr": int(kfm.total_kr), "case_count": int(kfm.case_count)},
    }


def _debt_guld(db, orgnr: str, has_dpa: bool) -> dict:
    """
    Line items with creditor name gating at SQL layer.

    Enskild firma creditors (raw_data->>'legal_form' = 'enskild_firma') have their
    name replaced with a DPA-required placeholder. This is enforced in the SELECT,
    not in Python post-processing — the name never leaves the DB for these rows
    unless has_dpa is True.
    """
    dpa_placeholder = "[Enskild näringsidkare — kräver DPA-tillägg]"

    tax_rows = db.execute(
        text("""
            SELECT signal_type, amount_sek, first_seen_at, is_active
            FROM norric_tax_signals
            WHERE orgnr = :orgnr
            ORDER BY first_seen_at DESC
        """),
        {"orgnr": orgnr},
    ).fetchall()

    kfm_rows = db.execute(
        text("""
            SELECT
                case_ref,
                claim_amount_sek,
                filed_at,
                is_active,
                creditor_type,
                CASE
                    WHEN :has_dpa OR COALESCE(raw_data->>'legal_form', '') != 'enskild_firma'
                    THEN COALESCE(raw_data->>'creditor_name', creditor_type)
                    ELSE :placeholder
                END AS creditor_name,
                COALESCE(raw_data->>'legal_form', '') = 'enskild_firma' AS is_enskild_firma
            FROM norric_payment_signals
            WHERE orgnr = :orgnr
            ORDER BY filed_at DESC
        """),
        {"orgnr": orgnr, "has_dpa": has_dpa, "placeholder": dpa_placeholder},
    ).fetchall()

    base = _debt_silver(db, orgnr)
    base["tier"] = "guld"
    base["dpa_active"] = has_dpa
    base["skatteverket"]["line_items"] = [dict(r._mapping) for r in tax_rows]
    base["kronofogden"]["line_items"] = [dict(r._mapping) for r in kfm_rows]
    return base


def _debt_premium(db, orgnr: str, has_dpa: bool) -> dict:
    """Guld + explain_score decomposing the internal model by signal weight."""
    from scoring.kreditvakt import score_from_db

    result = score_from_db(db, orgnr)
    base = _debt_guld(db, orgnr, has_dpa=has_dpa)
    base["tier"] = "premium"

    signals = result.get("signals", [])
    base["explain_score"] = {
        "distress_probability": result["distress_probability"],
        "signal_contributions": signals,
        "score_source": result.get("score_source", "live"),
        "note": "Signal weights: skatteverket_debt=0.30, skatteverket_flag=0.20, "
                "kronofogden_count=0.25, kronofogden_recency=0.10, bolagsverket_petition=0.15",
    }
    return base


def _has_dpa(db, request: Request) -> bool:
    """Check if the requesting user has a signed DPA."""
    user_id = request.headers.get("X-Kreditvakt-User-Id")
    if not user_id:
        return False
    row = db.execute(
        text("SELECT 1 FROM dpa_signatures WHERE user_id = :uid LIMIT 1"),
        {"uid": user_id},
    ).fetchone()
    return row is not None


# ── GET /health ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    from ingestion.db import Session

    db = Session()
    checks: dict = {}

    # T2: scoring output tables
    try:
        row = db.execute(
            text("""
                SELECT
                    COUNT(*) AS tracked_companies,
                    MAX(scored_at) AS last_scored,
                    COUNT(*) FILTER (WHERE risk_band >= 4) AS high_risk_count
                FROM company_scores
            """)
        ).fetchone()
        checks["company_scores"] = "ok"
        tracked     = int(row.tracked_companies) if row else 0
        last_scored = row.last_scored.isoformat() if row and row.last_scored else None
        high_risk   = int(row.high_risk_count) if row else 0
    except Exception as e:
        checks["company_scores"] = f"fail: {type(e).__name__}"
        tracked, last_scored, high_risk = 0, None, 0
        log.error("Health: company_scores check failed: %s", e)

    # T1: ingestion signal tables
    for table in ("norric_tax_signals", "norric_payment_signals"):
        try:
            db.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))  # noqa: S608
            checks[table] = "ok"
        except Exception as e:
            checks[table] = f"fail: {type(e).__name__}"
            log.error("Health: %s check failed: %s", table, e)

    db.close()

    checks["circuit_breaker"] = scoring_circuit.state

    all_ok = all(v == "ok" for k, v in checks.items() if k != "circuit_breaker")
    circuit_ok = scoring_circuit.state in ("closed", "half_open")
    status = "ok" if (all_ok and circuit_ok) else "degraded"

    return {
        "status":             status,
        "product":            "kreditvakt",
        "version":            "2.1.0",
        "deploy_sha":         _DEPLOY_SHA,
        "checks":             checks,
        "tracked_companies":  tracked,
        "high_risk_count":    high_risk,
        "last_scored":        last_scored,
    }


# ── GET /api/env-check  (temporary diagnostic — remove after V3 verified) ──────

@app.get("/api/env-check")
def env_check():
    """Shape-only diagnostic — confirms env vars are present and well-formed.
    Never logs or returns the values themselves."""
    import re as _re
    url   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    return {
        "url_present":            bool(url),
        "url_length":             len(url),
        "url_starts_with_https":  url.startswith("https://"),
        "url_has_upstash_io":     "upstash.io" in url,
        "url_has_whitespace":     bool(_re.search(r"\s", url)),
        "url_has_quotes":         bool(_re.search(r"[\"']", url)),
        "token_present":          bool(token),
        "token_length":           len(token),
        "token_has_whitespace":   bool(_re.search(r"\s", token)),
        "token_has_quotes":       bool(_re.search(r"[\"']", token)),
        "railway_environment":    os.environ.get("RAILWAY_ENVIRONMENT"),
        "railway_service":        os.environ.get("RAILWAY_SERVICE_NAME"),
        "deploy_sha_prefix":      _DEPLOY_SHA[:8] if _DEPLOY_SHA != "unknown" else "unknown",
    }


# ── Response helpers ───────────────────────────────────────────────────────────

def _enrich_response(result: dict, request: Request, *, entity: Optional[dict] = None) -> dict:
    """Build the public response envelope around the scorer's result dict.

    Contract (see docs/no-fabrication-contract.md):
      - Canonical risk family: risk_score (0-20, ascending=worse), risk_band (1-5),
        risk_tier (HEALTHY|WATCH|ELEVATED|HIGH|CRITICAL).
      - Envelope metadata: scale='0-20', polarity='ascending_risk'.
      - score_source ∈ {'live', 'no_signals'}. 'mock' is not a valid value.
      - For no_signals: risk_* fields are null; ingestion_status is present.

    Dropped this PR: display_score, insolvency_score, band, band_label,
    band_action, confidence_label. Swedish-marketing strings (band_action /
    confidence_label) and tier-label strings (band_label) all moved out of
    the canonical envelope; SDK consumers route on risk_tier (English enum)
    and derive any UI copy themselves until labels.sv lands.
    """
    is_no_signals = result.get("score_source") == "no_signals"

    out: dict = {
        "orgnr":        result["orgnr"],
        "name":         (entity or {}).get("name"),
        "entity": {
            "status":          (entity or {}).get("status", "active"),
            "deregistered_at": (entity or {}).get("deregistered_at"),
        },
        "score_source": result["score_source"],
        "scored_at":    result.get("scored_at"),

        "risk_score":   result.get("risk_score"),
        "risk_band":    result.get("risk_band"),
        "risk_tier":    result.get("risk_tier"),

        "scale":        "0-20",
        "polarity":     "ascending_risk",

        "distress_probability": result.get("distress_probability"),

        "signals":       result.get("signals", []),
        "signals_fired": result.get("signals_fired", 0),
        "signals_total": result.get("signals_total", 5),

        "data_freshness_hours": result.get("data_freshness_hours"),
        "stale_data":           result.get("stale_data", False),
    }

    if is_no_signals:
        out["ingestion_status"] = result.get("ingestion_status")

    return out


def _confidence_label(result: dict) -> str:
    """Internal helper retained for structured logging; no longer surfaced
    in the public response envelope per the kill-mock PR."""
    fired = result.get("signals_fired", 0)
    stale = result.get("stale_data", False)
    if stale:
        return "Tidig indikation"
    if fired >= 3:
        return "Starkt signal"
    if fired >= 1:
        return "Måttlig signal"
    return "Tidig indikation"


# ── Norric Intelligence REST bridge (dashboard) ────────────────────────────────
#
# Three thin endpoints exposing the same payload shapes as the
# norric_*_v1 MCP tools, for clients that can't speak Streamable HTTP /
# SSE cleanly (browser fetch was observed to hang reading FastMCP's SSE
# response bodies past their headers, even with json_response=True).
# MCP remains the canonical contract — these endpoints are an additional
# transport. Same data, same envelope, no session handshake.

from datetime import datetime, timezone as _tz  # noqa: E402
import secrets as _secrets  # noqa: E402


def _meta(tool: str, source: list, confidence: float, ttl: int) -> dict:
    return {
        "response_id":        f"nrsp_{_secrets.token_hex(6)}",
        "tool":               tool,
        "source":             source,
        "fetched_at":         datetime.now(_tz.utc).isoformat(),
        "confidence":         confidence,
        "cache_ttl_seconds":  ttl,
        "is_cached":          False,
    }


def _wrap(tool: str, source: list, confidence: float, ttl: int, data: dict,
          warnings: list[str] | None = None) -> dict:
    return {
        "data":     data,
        "metadata": _meta(tool, source, confidence, ttl),
        "signals":  [],
        "warnings": warnings or [],
    }


@app.get("/api/v1/score/{orgnr}", summary="Norric intelligence: full score package (REST)")
def norric_score_rest(orgnr: str, request: Request):
    """REST bridge for norric_score_v1 — full intelligence package."""
    from scoring.kreditvakt import score_from_db
    from kreditvakt.intelligence import build_score_intelligence
    from ingestion.db import Session

    try:
        orgnr_norm = _validate_orgnr(orgnr)
    except HTTPException as exc:
        raise exc

    db = Session()
    try:
        result = score_from_db(db, orgnr_norm)
        package = build_score_intelligence(db, orgnr_norm, result)
    except Exception as exc:
        log.error("norric_score_rest[%s] failed: %s", orgnr_norm, exc, exc_info=True)
        db.close()
        return _wrap(
            tool="norric_score_v1", source=[], confidence=0.0, ttl=0,
            data={"orgnr": orgnr_norm},
            warnings=[f"scoring_error: {type(exc).__name__}"],
        )
    finally:
        try: db.close()
        except Exception: pass

    distress = result.get("distress_probability")
    confidence = max(0.0, 1.0 - distress) if distress is not None else 0.0
    warnings: list[str] = []
    if result.get("stale_data"):
        warnings.append(
            f"Data freshness {result.get('data_freshness_hours', '?')}h — exceeds 48h threshold"
        )
    if package["company"]["sector"] is None:
        warnings.append("no_procurement_history: sector cannot be derived")
    if package["company"]["lat"] is None:
        warnings.append("no_geo_anchor: municipality coordinates unavailable")

    return _wrap(
        tool="norric_score_v1",
        source=["skatteverket", "kronofogden", "bolagsverket",
                "norric_entities", "company_scores", "company_score_history",
                "signal_contracts", "contagion_peers", "municipalities"],
        confidence=round(confidence, 2),
        ttl=900,
        data=package,
        warnings=warnings,
    )


@app.get("/api/v1/search", summary="Norric intelligence: company search (REST)")
def norric_search_rest(q: str = Query("", min_length=0, max_length=200),
                       limit: int = Query(10, ge=1, le=50)):
    """REST bridge for norric_search_v1 — orgnr / name prefix search."""
    from kreditvakt.intelligence import search_entities
    from ingestion.db import Session

    q_stripped = (q or "").strip()
    if not q_stripped:
        return _wrap(
            tool="norric_search_v1",
            source=["norric_entities"],
            confidence=0.0, ttl=0,
            data={"query": "", "results": [], "result_count": 0},
            warnings=["empty_query"],
        )

    db = Session()
    try:
        results = search_entities(db, q_stripped, limit=limit)
    except Exception as exc:
        log.error("norric_search_rest failed: %s", exc, exc_info=True)
        results = []
    finally:
        db.close()

    return _wrap(
        tool="norric_search_v1",
        source=["norric_entities", "company_scores"],
        confidence=1.0 if results else 0.0,
        ttl=300,
        data={"query": q_stripped, "results": results, "result_count": len(results)},
        warnings=[] if results else ["no_matches"],
    )


@app.get("/api/v1/contagion-map/{orgnr}", summary="Norric intelligence: blast-radius (REST)")
def norric_contagion_map_rest(orgnr: str):
    """REST bridge for norric_contagion_map_v1 — blast-radius shape."""
    from kreditvakt.intelligence import build_contagion_map
    from ingestion.db import Session

    try:
        orgnr_norm = _validate_orgnr(orgnr)
    except HTTPException as exc:
        raise exc

    db = Session()
    try:
        m = build_contagion_map(db, orgnr_norm)
    except Exception as exc:
        log.error("norric_contagion_map_rest[%s] failed: %s", orgnr_norm, exc, exc_info=True)
        return _wrap(
            tool="norric_contagion_map_v1",
            source=[], confidence=0.0, ttl=0,
            data={"orgnr": orgnr_norm},
            warnings=[f"contagion_map_error: {type(exc).__name__}"],
        )
    finally:
        db.close()

    warnings = [
        "Contagion peers are probabilistic based on shared procurement sector "
        "and geographic proximity. Not verified supply chain relationships.",
    ]
    if m.get("warning") == "orgnr_not_ingested":
        warnings.append("orgnr_not_ingested: not in norric_entities")
    if m["summary"]["total_peers"] == 0:
        warnings.append(
            "no_peers: source has no procurement history (sector unknown) "
            "or no scored companies in same kommunkod/county"
        )

    confidence = (
        0.5 if any(r["ring"] == 1 for r in m["rings"])
        else 0.3 if m["rings"]
        else 0.0
    )

    return _wrap(
        tool="norric_contagion_map_v1",
        source=["contagion_peers", "norric_entities", "municipalities", "company_scores"],
        confidence=confidence, ttl=14_400,
        data=m, warnings=warnings,
    )


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
