"""
Norric key issuance — email delivery via Resend.
"""
import logging
import os

log = logging.getLogger(__name__)

_FROM = "edgar@norric.io"
_QUOTA_BY_TIER = {"free": 10, "standard": None, "compliance": None}


def _body(raw_key: str, tier: str) -> str:
    quota = _QUOTA_BY_TIER.get(tier)
    quota_line = f"Monthly quota:    {quota} calls\n" if quota else ""
    return (
        f"Welcome to Norric.\n\n"
        f"Your Norric MCP API key ({tier} tier) is below.\n\n"
        f"  {raw_key}\n\n"
        f"Tier:             {tier.capitalize()}\n"
        f"{quota_line}"
        f"\n"
        f"Use the key in any MCP-compatible client:\n"
        f"  Authorization: Bearer {raw_key}\n"
        f"  -- or --\n"
        f"  X-Norric-Key: {raw_key}\n\n"
        f"MCP endpoint: https://norric-mcp-production.up.railway.app/mcp\n\n"
        f"Getting started: https://norric.io/developer-docs.html\n\n"
        f"Keep this key secret. Do not share it.\n"
        f"Compromised? Email hej@norric.io immediately.\n\n"
        f"Norric AB · Malmö, Sweden"
    )


def send_key_email(to_email: str, raw_key: str, tier: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        log.warning(
            f"[KEY_ISSUANCE] RESEND_API_KEY not set — skipping email to {to_email} "
            f"(tier={tier} key_prefix={raw_key[:8]}...)"
        )
        return

    try:
        import httpx

        resp = httpx.post(
            "https://api.resend.com/emails",
            json={
                "from": _FROM,
                "to": [to_email],
                "subject": "Your Norric MCP API Key",
                "text": _body(raw_key, tier),
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        log.info(f"[KEY_ISSUANCE] Email sent to {to_email} via Resend (tier={tier})")

    except Exception as exc:
        log.error(f"[KEY_ISSUANCE] Resend delivery failed to {to_email}: {exc}")
        # Do not raise — key is stored in DB and logged. Ops can resend manually.
