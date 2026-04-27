"""ePhorte DMS scraper."""
import logging
import re
from datetime import date
from pathlib import Path

import httpx
import yaml

log = logging.getLogger(__name__)
_SELECTORS_PATH = Path(__file__).parent.parent / "selectors.yaml"


def _load_selectors() -> dict:
    with open(_SELECTORS_PATH) as f:
        return yaml.safe_load(f)["ephorte"]


def _parse_date(text: str) -> date | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


class EphorteScraper:
    def __init__(self):
        self._sel = _load_selectors()

    async def fetch_recent(
        self,
        kommunkod: str,
        municipality_url: str,
        since: date,
        session: httpx.AsyncClient,
    ) -> list[dict]:
        results = []
        search_url = municipality_url.rstrip("/") + "/ephorte/search"

        try:
            resp = await session.get(search_url, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                log.warning("ephorte returned %d for %s", resp.status_code, municipality_url)
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            for row in soup.select(self._sel["case_list"]):
                case_id_el = row.select_one(self._sel["case_id"])
                title_el   = row.select_one(self._sel["title"])
                date_el    = row.select_one(self._sel["filed_at"])
                unit_el    = row.select_one(self._sel["handling_unit"])

                case_id = case_id_el.get_text(strip=True) if case_id_el else None
                title   = title_el.get_text(strip=True)   if title_el   else None
                filed   = _parse_date(date_el.get_text())  if date_el    else None
                unit    = unit_el.get_text(strip=True)     if unit_el    else None

                if filed and filed < since:
                    continue
                if case_id:
                    results.append({
                        "kommunkod": kommunkod,
                        "case_id":   case_id,
                        "title":     title,
                        "handling_unit": unit,
                        "filed_at":  filed,
                        "platform":  "ephorte",
                    })
        except Exception as exc:
            log.warning("ephorte scrape failed for %s: %s", municipality_url, exc)

        return results
