"""
Norric key issuance — email delivery via Resend.
"""
import logging
import os

log = logging.getLogger(__name__)

_FROM = "Kreditvakt <hej@norric.io>"
_FRONTEND = "https://kreditvakt.com"


def _subject(tier: str) -> str:
    return "Din Kreditvakt API-nyckel"


def _body(raw_key: str, tier: str) -> str:
    lookup_url = f"{_FRONTEND}/lookup?key={raw_key}"

    sections = [
        f"Välkommen till Kreditvakt.\n",
        # Section 1 — Sök direkt
        "-- Sök direkt ----------------------------------------",
        f"  {lookup_url}",
        "",
        "Klicka på länken ovan för att söka direkt med din nyckel förifylld.",
        "Sparar du inte länken? Du kan alltid gå till kreditvakt.com/lookup",
        "och klistra in din nyckel där.",
        "",
        # Section 2 — Din API-nyckel
        "-- Din API-nyckel ------------------------------------",
        f"  {raw_key}",
        "",
        "Spara nyckeln -- den visas inte igen.",
        "Komprometterad? Mejla hej@norric.io omedelbart.",
        "",
    ]

    if tier == "free":
        sections += [
            "-- Dina sökningar -----------------------------------",
            "Du har 10 sökningar i din Free-tier. Använd dem för att se hur",
            "Kreditvakt bedömer riskerna i din kundportfölj.",
            "",
        ]

    sections += [
        # Section 3 — För utvecklare
        "-- För utvecklare ------------------------------------",
        f"  Dokumentation: {_FRONTEND}/docs",
        f"  MCP-endpoint:  https://norric-mcp-production.up.railway.app/mcp",
        f"  Authorization: Bearer {raw_key}",
        "",
        # Footer
        "------------------------------------------------------",
        "Norric AB · Malmö · hej@norric.io",
    ]

    return "\n".join(sections)


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
                "subject": _subject(tier),
                "text": _body(raw_key, tier),
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        log.info(f"[KEY_ISSUANCE] Email sent to {to_email} via Resend (tier={tier})")

    except Exception as exc:
        log.error(f"[KEY_ISSUANCE] Resend delivery failed to {to_email}: {exc}")
        # Do not raise — key is in DB. Ops can resend manually.
