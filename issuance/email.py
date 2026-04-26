"""
Norric key issuance — email delivery.
"""
import logging
import os

log = logging.getLogger(__name__)


def send_key_email(to_email: str, raw_key: str, tier: str) -> None:
    """
    Send the API key to the customer.

    TODO: wire Sendgrid or SMTP.
    For now, log to stdout so Railway logs capture it.
    In production: never log raw keys — this is dev-only.
    """
    sendgrid_key = os.environ.get("SENDGRID_API_KEY", "")
    if sendgrid_key:
        _send_via_sendgrid(to_email, raw_key, tier, sendgrid_key)
    else:
        log.warning(
            f"[KEY_ISSUANCE] tier={tier} to={to_email} key_prefix={raw_key[:8]}... "
            "(set SENDGRID_API_KEY to enable email delivery)"
        )


def _send_via_sendgrid(to_email: str, raw_key: str, tier: str, api_key: str) -> None:
    try:
        import httpx

        body = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": "noreply@norric.io", "name": "Norric AB"},
            "subject": f"Your Norric API key — {tier} tier",
            "content": [
                {
                    "type": "text/plain",
                    "value": (
                        f"Welcome to Norric.\n\n"
                        f"Your API key ({tier} tier):\n\n"
                        f"  {raw_key}\n\n"
                        f"Include it in requests as:\n"
                        f"  Authorization: Bearer {raw_key}\n"
                        f"  -- or --\n"
                        f"  X-Norric-Key: {raw_key}\n\n"
                        f"Endpoint: https://norric-mcp-production.up.railway.app/mcp\n\n"
                        f"Documentation: https://norric.io/api\n\n"
                        f"Keep this key secret. Do not share it.\n"
                        f"If it is compromised, email hej@norric.io.\n\n"
                        f"Norric AB · Malmö, Sweden"
                    ),
                }
            ],
        }

        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        log.info(f"[KEY_ISSUANCE] Email sent to {to_email} (tier={tier})")

    except Exception as exc:
        log.error(f"[KEY_ISSUANCE] Email failed to {to_email}: {exc}")
        # Do not raise — key was already delivered via webhook response log.
        # Ops can retrieve from Railway logs and re-send manually.
