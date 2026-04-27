import asyncio
import logging
import io
from celery import shared_task
from sqlalchemy import text

import httpx

from ingestion.db import Session
from ingestion.boverket.energidekl_scraper import batch_scrape_energideklarationer
from ingestion.pipeline_run import pipeline_run

log = logging.getLogger(__name__)

KLIMATKLIVET_URL = "https://www.naturvardsverket.se/globalassets/data/klimatklivet-beviljade-projekt.xlsx"


@shared_task(name="boverket.scrape_energideklarationer")
def scrape_energideklarationer():
    """Weekly — fetch unprocessed properties and scrape their energideklarationer."""
    db = Session()
    try:
        with pipeline_run(db, "boverket_energidekl") as ctx:
            # Fetch unprocessed fastighetsbeteckningar
            rows = db.execute(
                text("""
                    SELECT p.fastighetsbeteckning
                    FROM norric_properties p
                    LEFT JOIN norric_grant_signals g
                        ON g.entity_id = p.fastighet_id
                        AND g.grant_type = 'energideklaration'
                    WHERE p.fastighetsbeteckning IS NOT NULL
                      AND g.id IS NULL
                    LIMIT 100
                """)
            ).fetchall()

            beteckningar = [r.fastighetsbeteckning for r in rows]
            if not beteckningar:
                log.info("no unprocessed properties for energideklaration")
                return {"processed": 0}

            results = asyncio.run(batch_scrape_energideklarationer(beteckningar))

            for res in results:
                db.execute(
                    text("""
                        INSERT INTO norric_grant_signals
                            (entity_id, entity_type, grant_type, energiklass, eu_deadline_flag, source)
                        VALUES
                            (:entity_id, 'property', 'energideklaration', :klass, :eu_flag, 'boverket_scrape')
                        ON CONFLICT (entity_id, grant_type, applied_at) DO NOTHING
                    """),
                    {
                        "entity_id": res["fastighetsbeteckning"],
                        "klass":     res.get("energiklass"),
                        "eu_flag":   res.get("eu_deadline_flag", False),
                    },
                )

            db.commit()
            ctx["rows_processed"] = len(beteckningar)
            ctx["rows_inserted"]  = len(results)
            return {"processed": len(beteckningar), "inserted": len(results)}
    finally:
        db.close()


@shared_task(name="boverket.ingest_klimatklivet")
def ingest_klimatklivet():
    """Monthly — download Klimatklivet grant Excel from Naturvårdsverket."""
    try:
        resp = httpx.get(KLIMATKLIVET_URL, timeout=60, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        log.error("failed to download Klimatklivet data: %s", exc)
        return {"error": str(exc)}

    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True)
        ws = wb.active
    except Exception as exc:
        log.error("failed to parse Klimatklivet Excel: %s", exc)
        return {"error": str(exc)}

    db = Session()
    try:
        with pipeline_run(db, "klimatklivet") as ctx:
            inserted = 0
            headers = None

            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [str(c).lower().strip() if c else "" for c in row]
                    continue

                if not headers:
                    continue

                row_dict = dict(zip(headers, row))
                orgnr_raw = str(row_dict.get("organisationsnummer") or "").replace("-", "").strip()
                if len(orgnr_raw) != 10:
                    continue

                amount_raw = row_dict.get("beviljat belopp") or row_dict.get("belopp")
                amount_sek = None
                if amount_raw:
                    try:
                        amount_sek = int(float(str(amount_raw).replace(" ", "").replace(",", ".")))
                    except ValueError:
                        pass

                approved_raw = row_dict.get("beslutsdatum")
                approved_at = None
                if approved_raw:
                    try:
                        from datetime import date
                        approved_at = date.fromisoformat(str(approved_raw)[:10])
                    except ValueError:
                        pass

                db.execute(
                    text("""
                        INSERT INTO norric_grant_signals
                            (entity_id, entity_type, grant_type, amount_sek, approved_at, status, source)
                        VALUES
                            (:orgnr, 'company', 'klimatklivet', :amount, :approved, 'approved', 'naturvardsverket')
                        ON CONFLICT (entity_id, grant_type, applied_at) DO NOTHING
                    """),
                    {"orgnr": orgnr_raw, "amount": amount_sek, "approved": approved_at},
                )
                inserted += 1

            db.commit()
            ctx["rows_processed"] = inserted
            ctx["rows_inserted"]  = inserted
            return {"inserted": inserted}
    finally:
        db.close()
