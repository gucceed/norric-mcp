"""
Norric key issuance service.

Separate Railway service (not the MCP server). Handles:
  GET  /checkout?tier={standard|compliance}&billing={monthly|annual}
       → Creates Stripe Checkout session, redirects browser

  POST /stripe/webhook
       → On checkout.session.completed: generates key, appends hash to
         NORRIC_API_KEYS (via Railway API or pending_keys.txt fallback),
         emails key to customer

  GET  /health → 200 OK

Environment variables required (set in Railway issuance service):
  STRIPE_SECRET_KEY
  STRIPE_WEBHOOK_SECRET
  STRIPE_PRICE_STANDARD_MONTHLY
  STRIPE_PRICE_STANDARD_ANNUAL
  STRIPE_PRICE_COMPLIANCE_MONTHLY
  STRIPE_PRICE_COMPLIANCE_ANNUAL
  RAILWAY_API_TOKEN        (optional — see _append_key_to_env)
  RAILWAY_SERVICE_ID       (optional — MCP server service ID)
  SENDGRID_API_KEY         (optional — falls back to stdout log)
"""
import logging
import os

import stripe
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from issuance.email import send_key_email
from issuance.key_gen import format_key_line, generate_api_key

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Norric Key Issuance", docs_url=None, redoc_url=None)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

PRICES = {
    ("standard",   "monthly"): {"amount_sek": 2_900,  "stripe_price_env": "STRIPE_PRICE_STANDARD_MONTHLY"},
    ("standard",   "annual"):  {"amount_sek": 29_000, "stripe_price_env": "STRIPE_PRICE_STANDARD_ANNUAL"},
    ("compliance", "monthly"): {"amount_sek": 9_900,  "stripe_price_env": "STRIPE_PRICE_COMPLIANCE_MONTHLY"},
    ("compliance", "annual"):  {"amount_sek": 99_000, "stripe_price_env": "STRIPE_PRICE_COMPLIANCE_ANNUAL"},
}

VALID_TIERS    = {"standard", "compliance"}
VALID_BILLINGS = {"monthly", "annual"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/checkout")
async def checkout(tier: str = "standard", billing: str = "monthly"):
    if tier not in VALID_TIERS:
        raise HTTPException(400, f"tier must be one of: {VALID_TIERS}")
    if billing not in VALID_BILLINGS:
        raise HTTPException(400, f"billing must be one of: {VALID_BILLINGS}")

    price_conf = PRICES[(tier, billing)]
    price_id = os.environ.get(price_conf["stripe_price_env"], "")
    if not price_id:
        raise HTTPException(500, f"Stripe price not configured for {tier}/{billing}")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url="https://norric.io/api/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="https://norric.io/api",
        metadata={"tier": tier, "billing": billing},
    )

    return RedirectResponse(session.url, status_code=303)


@app.post("/stripe/webhook")
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
    customer_email = session.get("customer_details", {}).get("email", "")
    tier = session.get("metadata", {}).get("tier", "standard")

    raw_key, _ = generate_api_key()
    label = f"{customer_email.replace('@', '_at_').replace('.', '_')}"
    key_line = format_key_line(raw_key, tier, label)

    _append_key_to_env(key_line, tier, customer_email)
    send_key_email(customer_email, raw_key, tier)

    log.info(f"[ISSUANCE] Key issued: tier={tier} to={customer_email}")


def _append_key_to_env(key_line: str, tier: str, email: str) -> None:
    """
    Append the new key hash line to NORRIC_API_KEYS on the MCP Railway service.

    Attempts Railway GraphQL API first. Falls back to writing pending_keys.txt
    which requires manual copy into Railway env — logged clearly for ops.

    Railway GraphQL mutation reference:
      https://docs.railway.app/reference/public-api#updating-a-variable
    """
    railway_token = os.environ.get("RAILWAY_API_TOKEN", "")
    service_id    = os.environ.get("RAILWAY_SERVICE_ID", "")

    if railway_token and service_id:
        try:
            import httpx

            # Fetch current value, append new line, write back
            # Railway API: serviceVariablesGet / serviceVariableUpsert
            gql = """
            mutation UpsertVariable($input: VariableUpsertInput!) {
              variableUpsert(input: $input)
            }
            """
            # We can't safely read-then-write without a race — append via
            # Railway PATCH requires the full current value. For MVP, log the
            # key line for manual insertion.
            # TODO: implement full read-modify-write using Railway API.
            raise NotImplementedError("Railway read-modify-write not yet implemented")

        except Exception as exc:
            log.warning(f"[ISSUANCE] Railway API update failed: {exc}. Falling back to file.")

    # Fallback: write to pending_keys.txt
    # Ops must copy these lines into NORRIC_API_KEYS in Railway dashboard.
    pending_path = os.path.join(os.path.dirname(__file__), "pending_keys.txt")
    with open(pending_path, "a") as f:
        f.write(key_line + "\n")

    log.warning(
        f"[ISSUANCE] KEY NOT AUTO-APPLIED. Copy this line into NORRIC_API_KEYS "
        f"in Railway dashboard for MCP service:\n  {key_line}\n"
        f"  (for customer: {email}, tier: {tier})"
    )
