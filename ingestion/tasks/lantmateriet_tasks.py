import logging
import os
from celery import shared_task
from sqlalchemy import text

from ingestion.db import Session
from ingestion.lantmateriet.open_fetcher import fetch_skane_properties
from ingestion.pipeline_run import pipeline_run

log = logging.getLogger(__name__)


@shared_task(name="lantmateriet.ingest_open")
def ingest_open_data():
    """Weekly — Wednesday 04:00. Fetches open WFS property data for Skåne."""
    db = Session()
    try:
        with pipeline_run(db, "lantmateriet_open") as ctx:
            inserted = 0
            for prop in fetch_skane_properties():
                db.execute(
                    text("""
                        INSERT INTO norric_properties
                            (fastighet_id, fastighetsbeteckning, kommunkod, county,
                             orgnr, owner_name, building_year, taxeringsvarde_sek,
                             area_sqm, coordinates_lat, coordinates_lon, source, licence_required)
                        VALUES
                            (:fastighet_id, :fastighetsbeteckning, :kommunkod, :county,
                             :orgnr, :owner_name, :building_year, :taxeringsvarde_sek,
                             :area_sqm, :coordinates_lat, :coordinates_lon, :source, :licence_required)
                        ON CONFLICT (fastighet_id) DO UPDATE SET
                            last_updated_at = now()
                    """),
                    prop,
                )
                inserted += 1

            db.commit()
            ctx["rows_processed"] = inserted
            ctx["rows_inserted"]  = inserted
            log.info("lantmateriet open: inserted %d properties", inserted)
            return {"inserted": inserted}
    finally:
        db.close()


@shared_task(name="lantmateriet.ingest_commercial")
def ingest_commercial():
    """
    Commercial Fastighetsregister — inactive until licence.
    Guarded by env var — will raise clearly if called without credentials.
    """
    if not os.environ.get("LANTMATERIET_CLIENT_ID"):
        raise RuntimeError(
            "Commercial licence not yet provisioned. "
            "Apply via partner@lm.se (4–8 week lead time). "
            "Task will activate automatically once env vars are set."
        )
    from ingestion.lantmateriet.commercial_fetcher import CommercialFetcher
    fetcher = CommercialFetcher()
    # TODO: implement fetch + upsert loop when licence confirmed
    raise NotImplementedError("Commercial fetcher implementation pending licence")
