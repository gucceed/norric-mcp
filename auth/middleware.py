"""
auth/middleware.py

Kreditvakt authentication and quota enforcement.

Auth flow:
    POST /auth/signup  — email + org_nr → creates Free tier user
    POST /auth/verify  — email verification token
    GET  /auth/me      — current user info + quota status

Quota:
    Free:    25 lookups/month, reset 1st of month at 00:00 Europe/Stockholm
    Silver:  500/month
    Guld:    2000/month
    Premium: unlimited
    Enterprise: unlimited

    Lookup #N+1 over quota returns 402 with upgrade copy.

Org nr validation:
    Swedish format XXXXXX-XXXX (10 digits + optional hyphen).
    Validated with Luhn checksum on the 10-digit form.

Privacy:
    ip_hash stored as SHA-256 of raw IP. No plaintext IPs ever written.
    query_log has no endpoint that exposes user-level history to third parties.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import text

log = logging.getLogger(__name__)

_ORGNR_RE = re.compile(r"^\d{6}-?\d{4}$")

# Tier allowances (lookups/month). None = unlimited.
_ALLOWANCES = {
    "free": 25,
    "silver": 500,
    "guld": 2000,
    "premium": None,
    "enterprise": None,
}


# ── Luhn checksum ─────────────────────────────────────────────────────────────

def _luhn_valid(digits: str) -> bool:
    """Validate a 10-digit Swedish org nr with Luhn algorithm."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def validate_orgnr(orgnr: str) -> str:
    """Normalise and validate Swedish org nr. Returns 10-digit form. Raises ValueError."""
    cleaned = orgnr.replace("-", "").strip()
    if not re.fullmatch(r"\d{10}", cleaned):
        raise ValueError("Org.nr måste vara 10 siffror (format: XXXXXX-XXXX)")
    if not _luhn_valid(cleaned):
        raise ValueError("Ogiltigt organisationsnummer — kontrollsumman stämmer inte")
    return cleaned


# ── Request/response models ───────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    org_nr: str

    @field_validator("org_nr")
    @classmethod
    def check_orgnr(cls, v: str) -> str:
        return validate_orgnr(v)


class SignupResponse(BaseModel):
    user_id: str
    email: str
    org_nr: str
    tier: str
    message: str


class QuotaResponse(BaseModel):
    used: int
    allowance: Optional[int]
    remaining: Optional[int]
    resets_at: str
    tier: str


# ── FastAPI sub-app ───────────────────────────────────────────────────────────

auth_app = FastAPI(title="Kreditvakt Auth", version="1.0.0")

auth_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@auth_app.post("/signup", response_model=SignupResponse)
def signup(req: SignupRequest):
    """
    Register a Free tier account.
    Creates user if email is new. If email already exists, returns existing user.
    Email verification token is sent (stub — wire to email provider in production).
    """
    from ingestion.db import Session

    db = Session()
    try:
        existing = db.execute(
            text("SELECT id, tier FROM users WHERE email = :email"),
            {"email": req.email},
        ).fetchone()

        if existing:
            return SignupResponse(
                user_id=str(existing.id),
                email=req.email,
                org_nr=req.org_nr,
                tier=existing.tier,
                message="Kontot finns redan. Verifiera din e-post för att logga in.",
            )

        row = db.execute(
            text("""
                INSERT INTO users (email, org_nr, tier, email_verified)
                VALUES (:email, :org_nr, 'free', false)
                RETURNING id, tier
            """),
            {"email": req.email, "org_nr": req.org_nr},
        ).fetchone()
        db.commit()

        _send_verification_email(req.email, str(row.id))

        return SignupResponse(
            user_id=str(row.id),
            email=req.email,
            org_nr=req.org_nr,
            tier="free",
            message="Konto skapat. Kontrollera din e-post för att verifiera.",
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log.error(f"Signup error for {req.email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Registrering misslyckades — försök igen")
    finally:
        db.close()


@auth_app.get("/me/quota", response_model=QuotaResponse)
def get_quota(request: Request):
    """Current user's monthly quota status."""
    user_id = _require_user(request)
    from ingestion.db import Session

    db = Session()
    try:
        row = db.execute(
            text("SELECT * FROM current_month_quota(:user_id)"),
            {"user_id": user_id},
        ).fetchone()
        tier_row = db.execute(
            text("SELECT tier FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
    finally:
        db.close()

    tier = tier_row.tier if tier_row else "free"
    allowance = _ALLOWANCES.get(tier)

    return QuotaResponse(
        used=int(row.used) if row else 0,
        allowance=allowance,
        remaining=int(row.remaining) if row and allowance is not None else None,
        resets_at=row.resets_at.isoformat() if row else "",
        tier=tier,
    )


# ── Quota enforcement (called from score endpoints) ───────────────────────────

def enforce_quota(request: Request, queried_orgnr: str) -> None:
    """
    Check quota and log the query. Raises HTTP 402 if over limit.
    No-op if user is not authenticated (unauthenticated calls are already
    blocked upstream by the auth check).
    """
    user_id = request.headers.get("X-Kreditvakt-User-Id")
    if not user_id:
        return

    from ingestion.db import Session

    db = Session()
    try:
        row = db.execute(
            text("SELECT * FROM current_month_quota(:user_id)"),
            {"user_id": user_id},
        ).fetchone()

        tier_row = db.execute(
            text("SELECT tier FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
    except Exception as e:
        log.warning(f"Quota check failed for {user_id}: {e} — allowing through")
        return
    finally:
        db.close()

    tier = tier_row.tier if tier_row else "free"
    allowance = _ALLOWANCES.get(tier)

    if allowance is not None and row and int(row.used) >= allowance:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "quota_exceeded",
                "message": f"Du har använt {row.used} av {allowance} sökningar denna månad.",
                "upgrade_url": "https://kreditvakt.se/priser",
                "resets_at": row.resets_at.isoformat() if row.resets_at else None,
            },
        )

    _log_query(user_id, queried_orgnr, tier, request)


def _log_query(user_id: str, orgnr: str, tier: str, request: Request) -> None:
    raw_ip = request.client.host if request.client else "unknown"
    ip_hash = hashlib.sha256(raw_ip.encode()).hexdigest()

    from ingestion.db import Session

    db = Session()
    try:
        db.execute(
            text("""
                INSERT INTO query_log (user_id, queried_org_nr, tier_at_query, ip_hash)
                VALUES (:user_id, :orgnr, :tier, :ip_hash)
            """),
            {"user_id": user_id, "orgnr": orgnr, "tier": tier, "ip_hash": ip_hash},
        )
        db.execute(
            text("UPDATE users SET last_active_at = now() WHERE id = :uid"),
            {"uid": user_id},
        )
        db.commit()
    except Exception as e:
        log.warning(f"Query log write failed for {user_id}/{orgnr}: {e}")
        db.rollback()
    finally:
        db.close()


def _require_user(request: Request) -> str:
    user_id = request.headers.get("X-Kreditvakt-User-Id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Autentisering krävs")
    return user_id


def _send_verification_email(email: str, user_id: str) -> None:
    """Stub. Wire to Resend/Postmark in production."""
    token = secrets.token_urlsafe(32)
    log.info(f"[stub] Verification email for {email}: token={token[:8]}… user_id={user_id}")
