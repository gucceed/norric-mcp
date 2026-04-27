"""
Skatteverket restanslängd (tax arrears register) scraper.

The restanslängd is a public register updated weekly. Skatteverket's
website renders results via a form POST + JavaScript. We use Playwright
for reliable extraction.

Returns a list of {orgnr, name, amount_sek} dicts.
"""
import logging
import re
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

log = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://www.skatteverket.se/foretagochorganisationer/skatter/"
    "betalningochdebitering/skattekontoochskattedeklaration/restlangd."
    "4.18e1b10334ebe8bc80004471.html"
)


def _normalise_orgnr(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return digits if len(digits) == 10 else raw


def _parse_amount(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


@retry(
    wait=wait_exponential(min=5, max=120),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _fetch_with_playwright() -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright not installed — run: pip install playwright && playwright install chromium")

    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(_SEARCH_URL, wait_until="networkidle", timeout=30000)

        # Detect whether the page has a search form or a downloadable list
        content = await page.content()
        if "restlängd" in content.lower() or "restlangd" in content.lower():
            log.info("restanslängd page loaded, attempting to extract data")

        # Attempt to find a table or list with orgnr + amounts
        rows = await page.query_selector_all("table tr, .result-row, .search-result")
        for row in rows:
            text_content = await row.text_content() or ""
            orgnr_match = re.search(r"\b(\d{6}-\d{4}|\d{10})\b", text_content)
            amount_match = re.search(r"([\d\s]+)\s*kr", text_content)
            if orgnr_match:
                results.append({
                    "orgnr": _normalise_orgnr(orgnr_match.group(1)),
                    "name": text_content.strip()[:100],
                    "amount_sek": _parse_amount(amount_match.group(1)) if amount_match else None,
                })

        await browser.close()

    log.info("scraped %d restanslängd entries", len(results))
    return results


async def fetch_restanslangd() -> list[dict]:
    """
    Primary entry point. Returns list of {orgnr, name, amount_sek}.

    NOTE: Skatteverket may require the user to accept terms or navigate
    a search form. If the scrape returns 0 results, check whether the
    page structure has changed and update the selectors in this module.
    """
    return await _fetch_with_playwright()
