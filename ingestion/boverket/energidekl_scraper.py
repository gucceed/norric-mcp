"""
Boverket energideklaration scraper.

Queries the public search at sokenergideklaration.boverket.se
by fastighetsbeteckning (from norric_properties).
Extracts: energiklass, primärenergital, utförd date, giltig_till.

Processes in batches of 100 per run. Skips properties already processed.
"""
import logging
import re
from datetime import date

log = logging.getLogger(__name__)

_SEARCH_URL = "https://sokenergideklaration.boverket.se/"
_EU_CLASSES_REQUIRING_UPGRADE = {"E", "F", "G"}


def _parse_energiklass(text: str) -> str | None:
    m = re.search(r"\bEnergiklass\s*:?\s*([A-G])\b", text, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _parse_date_field(text: str, label: str) -> date | None:
    m = re.search(rf"{label}\s*:?\s*(\d{{4}}-\d{{2}}-\d{{2}})", text, re.IGNORECASE)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


async def scrape_energideklaration(fastighetsbeteckning: str) -> dict | None:
    """Scrape one property's energideklaration. Returns None if not found."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright not installed")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(_SEARCH_URL, wait_until="networkidle", timeout=20000)

            # Fill the search field
            search_input = await page.query_selector(
                "input[name*='fastighet'], input[placeholder*='fastighet'], input[type='search']"
            )
            if not search_input:
                log.warning("no search input found on Boverket energideklaration page")
                return None

            await search_input.fill(fastighetsbeteckning)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2000)

            content = await page.content()
            energiklass = _parse_energiklass(content)
            utford = _parse_date_field(content, "utförd")
            giltig_till = _parse_date_field(content, "giltig till")

            if not energiklass:
                return None

            return {
                "fastighetsbeteckning": fastighetsbeteckning,
                "energiklass":         energiklass,
                "eu_deadline_flag":    energiklass in _EU_CLASSES_REQUIRING_UPGRADE,
                "utford_date":         utford,
                "giltig_till":         giltig_till,
            }
        finally:
            await browser.close()


async def batch_scrape_energideklarationer(
    fastighetsbeteckningar: list[str],
) -> list[dict]:
    """Scrape up to 100 properties per call."""
    results = []
    for fb in fastighetsbeteckningar[:100]:
        try:
            result = await scrape_energideklaration(fb)
            if result:
                results.append(result)
        except Exception as exc:
            log.warning("failed to scrape %s: %s", fb, exc)
    return results
