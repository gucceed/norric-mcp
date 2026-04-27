"""
Lantmäteriet commercial Fastighetsregister fetcher.

STUB — will be activated when commercial licence is confirmed.
Apply via partner@lm.se (4–8 week lead time).

When activated, enriches existing norric_properties rows with:
orgnr, owner_name, building_year, taxeringsvarde_sek.
"""
import os


class CommercialFetcher:
    BASE = "https://api.lantmateriet.se"

    def __init__(self):
        self._client_id = os.environ.get("LANTMATERIET_CLIENT_ID")
        self._client_secret = os.environ.get("LANTMATERIET_CLIENT_SECRET")
        if not self._client_id:
            raise RuntimeError(
                "LANTMATERIET_CLIENT_ID not set. "
                "Commercial licence required — apply via partner@lm.se"
            )

    async def _get_token(self) -> str:
        import httpx
        resp = httpx.post(
            f"{self.BASE}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def fetch_fastighetsregister(self, kommunkod: str) -> list[dict]:
        # TODO: implement when licence confirmed
        # Endpoint TBD from Lantmäteriet API documentation
        raise NotImplementedError("Commercial licence pending — apply via partner@lm.se")
