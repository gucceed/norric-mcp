"""Lex DMS scraper."""
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
        return yaml.safe_load(f)["lex"]


def _parse_date(text: str) -> date | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


class LexScraper:
    def __init__(self):
        self._sel = _load_selectors()

    async def fetch_recent(
        self,
        kommunkod: str,
        municipality_url: str,
        since: date,
        session: httpx.AsyncClient,
    ) -> list[dict]:
        from playwright.async_api import async_playwright

        results = []
        url = municipality_url.rstrip("/") + "/lex/"

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=20000)
                rows = await page.query_selector_all(self._sel["case_list"])

                for row in rows:
                    case_id_el = await row.query_selector(self._sel["case_id"])
                    title_el   = await row.query_selector(self._sel["title"])
                    date_el    = await row.query_selector(self._sel["filed_at"])
                    unit_el    = await row.query_selector(self._sel["handling_unit"])

                    case_id = (await case_id_el.text_content() or "").strip() if case_id_el else None
                    title   = (await title_el.text_content() or "").strip() if title_el else None
                    filed   = _parse_date(await date_el.text_content() or "") if date_el else None
                    unit    = (await unit_el.text_content() or "").strip() if unit_el else None

                    if filed and filed < since:
                        continue
                    if case_id:
                        results.append({
                            "kommunkod": kommunkod,
                            "case_id":   case_id,
                            "title":     title,
                            "handling_unit": unit,
                            "filed_at":  filed,
                            "platform":  "lex",
                        })
            finally:
                await browser.close()

        return results
