"""
billing/stripe_products.py

Stripe product/price management for Kreditvakt.

Annual-only contracts. No monthly billing option.
Enterprise has no Stripe SKU — tier set manually after contract signing.

Products:
    silver_499_annual    — 499 kr/year
    guld_1499_annual     — 1499 kr/year
    premium_4999_annual  — 4999 kr/year

5 kr per-search SKU: archived in Stripe (not deleted — preserves audit trail).

Env vars required:
    STRIPE_SECRET_KEY  — test mode for staging, live for production
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

# Maps Stripe price_id (set in env) to internal tier name
_PRICE_TO_TIER: dict[str, str] = {}


def _stripe():
    import stripe
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY not set")
    stripe.api_key = key
    return stripe


def get_checkout_url(tier: str, user_id: str, email: str) -> str:
    """
    Create a Stripe Checkout session for the given tier.
    Returns the checkout URL to redirect the user to.
    """
    price_id = _price_id_for_tier(tier)
    if not price_id:
        raise ValueError(f"No Stripe price configured for tier: {tier}")

    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=email,
        metadata={"user_id": user_id, "tier": tier},
        success_url="https://kreditvakt.se/priser?upgraded=1",
        cancel_url="https://kreditvakt.se/priser?cancelled=1",
    )
    return session.url


def _price_id_for_tier(tier: str) -> Optional[str]:
    mapping = {
        "silver": os.environ.get("STRIPE_PRICE_SILVER"),
        "guld": os.environ.get("STRIPE_PRICE_GULD"),
        "premium": os.environ.get("STRIPE_PRICE_PREMIUM"),
    }
    return mapping.get(tier)
