"""Diarium crawler Celery tasks — Skåne first, then all Sweden."""
import asyncio
import logging
from datetime import date, timedelta

import httpx
from celery import shared_task
from sqlalchemy import text

from ingestion.db import Session
from ingestion.diarium.platform_detector import detect_platform
from ingestion.diarium.scrapers.platina import PlatinaScraper
from ingestion.diarium.scrapers.evolution import EvolutionScraper
from ingestion.diarium.scrapers.lex import LexScraper
from ingestion.diarium.scrapers.ephorte import EphorteScraper
from ingestion.diarium.tagger import tag_case
from ingestion.pipeline_run import pipeline_run

log = logging.getLogger(__name__)

# Skåne municipalities: kommunkod → (municipality name, diarium URL)
SKANE_MUNICIPALITIES: dict[str, tuple[str, str]] = {
    "1230": ("Burlöv",         "https://www.burlov.se/kommunpolitik/kallelser-och-protokoll/diarium.html"),
    "1231": ("Landskrona",     "https://www.landskrona.se/diarium"),
    "1233": ("Vellinge",       "https://www.vellinge.se/kommunen/fortroendevalda/naemnder-och-styrelser/diarium"),
    "1256": ("Östra Göinge",   "https://www.ostragoinge.se/naringsliv-och-arbete/diarium"),
    "1260": ("Örkelljunga",    "https://www.orkelljunga.se"),
    "1261": ("Kävlinge",       "https://www.kavlinge.se/kommunen/politik/diarium"),
    "1262": ("Lomma",          "https://www.lomma.se/kommunen/kommunens-organisation/diarium"),
    "1263": ("Svedala",        "https://www.svedala.se"),
    "1264": ("Skurup",         "https://www.skurup.se"),
    "1265": ("Sjöbo",          "https://www.sjobo.se"),
    "1266": ("Hörby",          "https://www.horby.se"),
    "1267": ("Höör",           "https://www.hoor.se"),
    "1270": ("Tomelilla",      "https://www.tomelilla.se"),
    "1272": ("Bromölla",       "https://www.bromolla.se"),
    "1273": ("Osby",           "https://www.osby.se"),
    "1275": ("Perstorp",       "https://www.perstorp.se"),
    "1276": ("Klippan",        "https://www.klippan.se"),
    "1277": ("Åstorp",         "https://www.astorp.se"),
    "1278": ("Bjuv",           "https://www.bjuv.se"),
    "1280": ("Malmö",          "https://malmo.se/Kommunpolitik/Diarium.html"),
    "1281": ("Lund",           "https://www.lund.se/kommunpolitik/diarium"),
    "1282": ("Eslöv",          "https://www.eslov.se/kommunen/diarium"),
    "1283": ("Helsingborg",    "https://helsingborg.se/styra-och-stodja/diarium"),
    "1284": ("Höganäs",        "https://www.hoganas.se/kommunen/diarium"),
    "1285": ("Eslöv",          "https://www.eslov.se"),
    "1286": ("Staffanstorp",   "https://www.staffanstorp.se"),
    "1287": ("Trelleborg",     "https://www.trelleborg.se"),
    "1290": ("Kristianstad",   "https://www.kristianstad.se/kommunen/diarium"),
    "1291": ("Hässleholm",     "https://hassleholm.se"),
    "1292": ("Simrishamn",     "https://www.simrishamn.se"),
    "1293": ("Ystad",          "https://www.ystad.se"),
    "1315": ("Hylte",          "https://www.hylte.se"),
}

_SCRAPER_MAP = {
    "platina":   PlatinaScraper,
    "evolution": EvolutionScraper,
    "lex":       LexScraper,
    "ephorte":   EphorteScraper,
}


async def _crawl_one(kommunkod: str, municipality: str, url: str, db, run_id, since: date) -> int:
    async with httpx.AsyncClient() as session:
        platform = await detect_platform(url, session)

    scraper_cls = _SCRAPER_MAP.get(platform)
    if not scraper_cls:
        log.warning("no scraper for platform %s at %s", platform, url)
        return 0

    scraper = scraper_cls()
    async with httpx.AsyncClient() as session:
        cases = await scraper.fetch_recent(kommunkod, url, since, session)

    inserted = 0
    for case in cases:
        title = case.get("title") or ""
        tags = tag_case(title)

        db.execute(
            text("""
                INSERT INTO norric_diarium_cases
                    (kommunkod, municipality, case_id, title, handling_unit,
                     filed_at, subject_tags, platform, source_url)
                VALUES
                    (:kommunkod, :municipality, :case_id, :title, :handling_unit,
                     :filed_at, :tags, :platform, :source_url)
                ON CONFLICT (kommunkod, case_id) DO UPDATE SET
                    title        = EXCLUDED.title,
                    subject_tags = EXCLUDED.subject_tags,
                    scraped_at   = now()
            """),
            {
                "kommunkod":     kommunkod,
                "municipality":  municipality,
                "case_id":       case.get("case_id"),
                "title":         title[:500] if title else None,
                "handling_unit": case.get("handling_unit"),
                "filed_at":      case.get("filed_at"),
                "tags":          tags,
                "platform":      platform,
                "source_url":    url,
            },
        )
        inserted += 1

    db.commit()
    return inserted


@shared_task(name="diarium.crawl_municipality")
def crawl_municipality(kommunkod: str):
    entry = SKANE_MUNICIPALITIES.get(kommunkod)
    if not entry:
        raise ValueError(f"Unknown kommunkod: {kommunkod}")
    municipality, url = entry
    since = date.today() - timedelta(days=7)

    db = Session()
    try:
        with pipeline_run(db, f"diarium_{kommunkod}") as ctx:
            count = asyncio.run(_crawl_one(kommunkod, municipality, url, db, ctx["run_id"], since))
            ctx["rows_inserted"] = count
            ctx["rows_processed"] = count
        return {"kommunkod": kommunkod, "inserted": count}
    finally:
        db.close()


@shared_task(name="diarium.crawl_all_skane")
def crawl_all_skane():
    results = {}
    for kommunkod in SKANE_MUNICIPALITIES:
        try:
            results[kommunkod] = crawl_municipality(kommunkod)
        except Exception as exc:
            log.error("diarium %s failed: %s", kommunkod, exc)
            results[kommunkod] = {"error": str(exc)}
    return results


@shared_task(name="diarium.crawl_all_sweden")
def crawl_all_sweden():
    # Activate after Skåne is stable — extend MUNICIPALITIES dict to all 290
    raise NotImplementedError("Activate after Skåne pilot is validated")
