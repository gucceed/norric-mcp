#!/usr/bin/env python3
"""
Fetch Bolagsverket reference documentation via Playwright.

CAPTCHA handling: opens a headed Chromium window the first time so Edgar can
solve any "are you human" challenges interactively. After each page.goto(),
the script polls the DOM for two conditions to be simultaneously true:
  - body innerText does NOT contain CAPTCHA markers
  - body innerText is substantive (>500 chars)
Once both hold, the script saves the page HTML and moves on. Storage state
is persisted to playwright-state.json so subsequent runs can be headless.

Run from anywhere — paths are absolute.

Usage:
  python3 scripts/fetch_bolagsverket_docs.py
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

REPO_ROOT = Path("/Users/admin/Code/norric-mcp")
REFERENCE_DIR = REPO_ROOT / "ingestion" / "bolagsverket" / "reference"
STATE_FILE = REPO_ROOT / "scripts" / "playwright-state.json"

URLS_TO_FETCH = [
    # Strategy: fetch known-good pages first (these have stable .html URLs and
    # are the canonical entry points for open-data and bulk-file information).
    # The legacy snr.bolagsverket.se help endpoints (rubriceringskoder,
    # foretagsstatus) are dead (503); their content may now be linked from
    # these pages or may have been migrated to PDFs we can discover by reading
    # what these pages say.
    (
        "nedladdningsbara_filer.html",
        "https://bolagsverket.se/apierochoppnadata/nedladdningsbarafiler.2517.html",
    ),
    (
        "api_vardefulla_datamangder.html",
        "https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/vardefulladatamangder/apiforvardefulladatamangder.5513.html",
    ),
    (
        "api_foretagsinformation.html",
        "https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/apiforatthamtaforetagsinformation.3988.html",
    ),
]

# Conditions: CAPTCHA marker absent AND content substantive
RESOLVED_PREDICATE = """
() => {
    if (!document.body) return false;
    const text = (document.body.innerText || '').toLowerCase();
    const captchaMarkers = [
        'this question is for testing whether you are a human visitor',
        'captcha',
        'är du en människa',
        'verifiering',
    ];
    const hasCaptcha = captchaMarkers.some(m => text.includes(m));
    const hasContent = (document.body.innerText || '').length > 500;
    return !hasCaptcha && hasContent;
}
"""


async def fetch_one(context, filename: str, url: str) -> str:
    out_path = REFERENCE_DIR / filename
    print(f"[fetch] {filename}")
    print(f"  url: {url}")

    # Fresh page per URL so error states don't bleed across navigations
    page = await context.new_page()
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except PWTimeout:
            print("  warn: domcontentloaded timeout, continuing")
        except Exception as e:
            print(f"  error: navigation failed: {e}")
            return f"navigation_failed: {e}"

        # Let any client-side redirects + CAPTCHA frames settle
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except PWTimeout:
            pass
        await asyncio.sleep(2)

        # Diagnostic: is a CAPTCHA gate visible right now?
        try:
            initial_text = (await page.evaluate("document.body.innerText || ''")).lower()
        except Exception:
            initial_text = ""
        captcha_markers = (
            "this question is for testing whether you are a human visitor",
            "captcha",
        )
        if any(m in initial_text for m in captcha_markers):
            print(
                "  CAPTCHA detected — solve it in the visible browser window.\n"
                "  Script will auto-continue when content loads. Timeout: 5 min."
            )

        # Wait for substantive non-CAPTCHA content
        try:
            await page.wait_for_function(RESOLVED_PREDICATE, timeout=300_000)
        except PWTimeout:
            print("  warn: page did not resolve to substantive content within 5 min")

        # Save whatever we have (timeout or success — both worth keeping for triage)
        content = await page.content()
        out_path.write_text(content, encoding="utf-8")
        print(f"  saved: {out_path}  ({len(content):,} bytes)")
        return "ok"
    finally:
        await page.close()


async def main() -> int:
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    has_state = STATE_FILE.exists()
    headless = has_state  # headed on first run, headless after

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_args = {}
        if has_state:
            context_args["storage_state"] = str(STATE_FILE)
        # Persona settings that look human
        context_args["user_agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        context_args["locale"] = "sv-SE"
        context = await browser.new_context(**context_args)

        if not has_state:
            print(
                "[mode] headed (first run) — Edgar may need to solve a CAPTCHA "
                "in the popup window the first time it appears.\n"
                "[mode] After solving once, the script auto-continues for all "
                "subsequent fetches in this run.\n"
            )
        else:
            print("[mode] headless (reusing saved storage state)\n")

        for filename, url in URLS_TO_FETCH:
            await fetch_one(context, filename, url)

        # Persist session for future runs
        await context.storage_state(path=str(STATE_FILE))
        print(f"\n[state] saved storage state to {STATE_FILE}")

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
