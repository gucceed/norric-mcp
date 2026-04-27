"""
Boverket API client — STUB pending licence.

Apply at: https://www.boverket.se/sv/energideklaration/
ETA: 6 weeks from application date.

Shares the same writer as energidekl_scraper — swapping source
only requires changing the fetcher, not the schema or tasks.
"""
import os


class BoverketApiClient:
    BASE = "https://api.boverket.se"

    def __init__(self):
        self._cid = os.environ.get("BOVERKET_CLIENT_ID")
        self._sec = os.environ.get("BOVERKET_CLIENT_SECRET")
        if not self._cid:
            raise RuntimeError("BOVERKET_CLIENT_ID not set — API licence pending")

    async def get_energideklaration(
        self,
        fastighetsbeteckning: str | None = None,
        orgnr: str | None = None,
    ) -> dict | None:
        # TODO: implement when licence arrives
        raise NotImplementedError("Boverket API licence pending")
