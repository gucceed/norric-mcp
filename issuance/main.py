"""
Norric key issuance service.

Endpoints:
  GET  /checkout?tier={standard|compliance}&billing={monthly|annual}&org_nr={10-digit}
       → Creates Stripe Checkout session, redirects browser

  POST /webhooks/stripe
       → checkout.session.completed: generate key, store in DB, email customer

  POST /signup/free
       → Takes {email, org_nr}, validates org_nr, generates key immediately

  GET  /health → 200 OK

Environment variables:
  STRIPE_SECRET_KEY
  STRIPE_WEBHOOK_SECRET
  STRIPE_PRICE_ID_MCP_STANDARD_MONTHLY
  STRIPE_PRICE_ID_MCP_STANDARD_ANNUAL
  STRIPE_PRICE_ID_MCP_COMPLIANCE_MONTHLY
  STRIPE_PRICE_ID_MCP_COMPLIANCE_ANNUAL
  RESEND_API_KEY     (optional — falls back to stdout log)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re

import stripe
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import text

from issuance.email import send_key_email
from issuance.key_gen import generate_api_key, hash_key

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Norric Key Issuance", docs_url=None, redoc_url=None)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

_PRICE_ENV = {
    ("standard",   "monthly"): "STRIPE_PRICE_ID_MCP_STANDARD_MONTHLY",
    ("standard",   "annual"):  "STRIPE_PRICE_ID_MCP_STANDARD_ANNUAL",
    ("compliance", "monthly"): "STRIPE_PRICE_ID_MCP_COMPLIANCE_MONTHLY",
    ("compliance", "annual"):  "STRIPE_PRICE_ID_MCP_COMPLIANCE_ANNUAL",
}

_ORG_NR_RE = re.compile(r"^\d{10}$")


def _validate_org_nr(org_nr: str) -> str:
    cleaned = re.sub(r"[-\s]", "", org_nr)
    if not _ORG_NR_RE.match(cleaned):
        raise ValueError("org_nr must be exactly 10 digits")
    return cleaned


def _store_key(key_hash: str, tier: str, email: str, org_nr: str | None) -> None:
    from ingestion.db import Session
    db = Session()
    try:
        db.execute(
            text("""
                INSERT INTO api_keys (key_hash, tier, org_nr, email, status)
                VALUES (:h, :tier, :org_nr, :email, 'active')
                ON CONFLICT (key_hash) DO NOTHING
            """),
            {"h": key_hash, "tier": tier, "org_nr": org_nr, "email": email},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _free_org_exists(org_nr: str) -> bool:
    """Return True if this org_nr already has an active free-tier key."""
    from ingestion.db import Session
    db = Session()
    try:
        row = db.execute(
            text("SELECT 1 FROM api_keys WHERE org_nr = :o AND tier = 'free' AND status = 'active' LIMIT 1"),
            {"o": org_nr},
        ).fetchone()
        return row is not None
    finally:
        db.close()


def _issue_key(tier: str, email: str, org_nr: str | None) -> str:
    """Generate, store, and email a key. Returns the raw key."""
    raw_key, key_hash = generate_api_key()
    _store_key(key_hash, tier, email, org_nr)
    send_key_email(email, raw_key, tier)
    log.info(f"[ISSUANCE] Key issued tier={tier} to={email}")
    return raw_key


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/checkout")
async def checkout(
    tier: str = "standard",
    billing: str = "monthly",
    org_nr: str = "",
):
    if tier not in ("standard", "compliance"):
        raise HTTPException(400, "tier must be standard or compliance")
    if billing not in ("monthly", "annual"):
        raise HTTPException(400, "billing must be monthly or annual")

    price_env = _PRICE_ENV[(tier, billing)]
    price_id = os.environ.get(price_env, "")
    if not price_id:
        raise HTTPException(500, f"Stripe price not configured ({price_env})")

    metadata: dict = {"tier": tier, "billing": billing}
    if org_nr:
        try:
            metadata["org_nr"] = _validate_org_nr(org_nr)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url="https://norric.io/api/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="https://norric.io/api",
        metadata=metadata,
    )

    return RedirectResponse(session.url, status_code=303)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid Stripe signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        _handle_completed_checkout(session)

    return Response(status_code=200)


def _handle_completed_checkout(session: dict) -> None:
    email = session.get("customer_details", {}).get("email", "")
    meta = session.get("metadata", {}) or {}
    tier = meta.get("tier", "standard")
    org_nr = meta.get("org_nr") or None

    if not email:
        log.warning(f"[ISSUANCE] checkout.session.completed with no email: {session.get('id')}")
        return

    _issue_key(tier, email, org_nr)


class FreeSignupRequest(BaseModel):
    email: str
    org_nr: str = ""
    company: str = ""
    use_case: str = ""

    @field_validator("org_nr")
    @classmethod
    def validate_org_nr(cls, v: str) -> str:
        if not v:
            return v
        cleaned = re.sub(r"[-\s]", "", v)
        if not _ORG_NR_RE.match(cleaned):
            raise ValueError("org_nr must be exactly 10 digits")
        return cleaned

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("invalid email address")
        return v.lower().strip()


@app.post("/signup/free", status_code=201)
async def signup_free(body: FreeSignupRequest):
    if body.org_nr and _free_org_exists(body.org_nr):
        raise HTTPException(
            status_code=409,
            detail="Din organisation har redan ett konto. Logga in eller uppgradera din plan.",
        )
    org_nr = body.org_nr or None
    raw_key = _issue_key("free", body.email, org_nr)
    return {
        "tier": "free",
        "api_key": raw_key,
        "message": (
            "Keep this key secret — it will not be shown again. "
            "A copy has been sent to your email address."
        ),
        "docs": "https://kreditvakt.com/docs",
    }
