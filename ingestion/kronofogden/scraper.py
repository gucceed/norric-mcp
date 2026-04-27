"""
Kronofogden betalningsförelägganden (payment orders) scraper.

Kronofogden's public register is accessible at kronofogden.se.
The search interface is JS-rendered; we use Playwright.
Returns a list of individual case dicts (one entity may have many cases).
"""
import logging
import re
from datetime import date
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

log = logging.getLogger(__name__)

_SEARCH_URL = "https://www.kronofogden.se/sv/foretag/skuld-och-betalning/betala-skulder-och-avgifter/betalningsforelaggande"


def _normalise_orgnr(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return digits if len(digits) == 10 else raw


def _parse_amount(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_date(text: str) -> date | None:
    import re as _re
    m = _re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def _classify_creditor(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["staten", "skatteverket", "kronofogden", "myndighet"]):
        return "state"
    if re.search(r"\b(ab|aktiebolag|hb|kb|ef)\b", t):
        return "company"
    return "private"


@retry(
    wait=wait_exponential(min=5, max=120),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _scrape_cases() -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright not installed")

    cases = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(_SEARCH_URL, wait_until="networkidle", timeout=30000)

        content = await page.content()
        log.debug("page loaded, content length=%d", len(content))

        rows = await page.query_selector_all("table tr, .case-row, .result-item")
        for row in rows:
            text_content = await row.text_content() or ""
            orgnr_match = re.search(r"\b(\d{6}-\d{4}|\d{10})\b", text_content)
            if not orgnr_match:
                continue

            amount_match = re.search(r"([\d\s]+)\s*kr", text_content)
            case_ref_match = re.search(r"[A-Z]{2,}\d+[-/]\d+", text_content)

            cases.append({
                "orgnr":           _normalise_orgnr(orgnr_match.group(1)),
                "case_ref":        case_ref_match.group(0) if case_ref_match else None,
                "creditor_type":   _classify_creditor(text_content),
                "claim_amount_sek": _parse_amount(amount_match.group(1)) if amount_match else None,
                "filed_at":        _parse_date(text_content),
            })

        await browser.close()

    log.info("scraped %d kronofogden cases", len(cases))
    return cases


async def fetch_payment_orders() -> list[dict]:
    """Primary entry point. Returns list of case dicts."""
    return await _scrape_cases()
