"""
billing/webhooks.py

Stripe webhook handler.

Handles:
    checkout.session.completed  — upgrade user tier in DB
    customer.subscription.deleted — downgrade to free

Mount at POST /billing/webhook in the main FastAPI app.

Env vars:
    STRIPE_WEBHOOK_SECRET  — from Stripe dashboard → Webhooks → signing secret
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

log = logging.getLogger(__name__)

webhook_app = FastAPI()


@webhook_app.post("/webhook")
async def stripe_webhook(request: Request):
    import stripe

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except stripe.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"])
    elif event["type"] == "customer.subscription.deleted":
        _handle_subscription_deleted(event["data"]["object"])

    return {"received": True}


def _handle_checkout_completed(session: dict) -> None:
    user_id = session.get("metadata", {}).get("user_id")
    tier = session.get("metadata", {}).get("tier")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")

    if not user_id or not tier:
        log.warning(f"Checkout completed without user_id/tier metadata: {session.get('id')}")
        return

    from ingestion.db import Session

    db = Session()
    try:
        db.execute(
            text("""
                UPDATE users
                SET tier = :tier,
                    stripe_subscription_id = :sub_id,
                    stripe_customer_id = :cust_id,
                    updated_at = now()
                WHERE id = :user_id
            """),
            {"tier": tier, "sub_id": subscription_id, "cust_id": customer_id, "user_id": user_id},
        )
        db.commit()
        log.info(f"User {user_id} upgraded to {tier} via Stripe checkout {session.get('id')}")
    except Exception as e:
        db.rollback()
        log.error(f"Failed to upgrade user {user_id} to {tier}: {e}", exc_info=True)
    finally:
        db.close()


def _handle_subscription_deleted(subscription: dict) -> None:
    sub_id = subscription.get("id")
    if not sub_id:
        return

    from ingestion.db import Session

    db = Session()
    try:
        db.execute(
            text("""
                UPDATE users
                SET tier = 'free', stripe_subscription_id = NULL, updated_at = now()
                WHERE stripe_subscription_id = :sub_id
            """),
            {"sub_id": sub_id},
        )
        db.commit()
        log.info(f"Subscription {sub_id} cancelled — user downgraded to free")
    except Exception as e:
        db.rollback()
        log.error(f"Failed to downgrade on subscription deletion {sub_id}: {e}", exc_info=True)
    finally:
        db.close()
