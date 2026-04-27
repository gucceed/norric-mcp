import logging
from celery import shared_task
from sqlalchemy import text

from ingestion.db import Session
from ingestion.scb.fetcher import ScbFetcher
from ingestion.scb.tables import SCB_TABLES, SCB_TABLE_MAP
from ingestion.pipeline_run import pipeline_run

log = logging.getLogger(__name__)


def _upsert_observations(db, observations: list[dict]) -> dict:
    stats = {"inserted": 0, "skipped": 0}
    for obs in observations:
        result = db.execute(
            text("""
                INSERT INTO norric_scb_observations
                    (table_id, period, region_kod, dimension_key, dimension_val, value, unit)
                VALUES
                    (:table_id, :period, :region_kod, :dimension_key, :dimension_val, :value, :unit)
                ON CONFLICT (table_id, period, region_kod, dimension_key, dimension_val)
                DO UPDATE SET value = EXCLUDED.value
                RETURNING (xmax = 0) AS is_insert
            """),
            obs,
        ).fetchone()
        if result and result.is_insert:
            stats["inserted"] += 1
        else:
            stats["skipped"] += 1
    db.commit()
    return stats


@shared_task(name="scb.ingest_table")
def scb_ingest_table(table_id: str):
    """Ingest a single SCB table."""
    config = SCB_TABLE_MAP.get(table_id)
    if not config:
        raise ValueError(f"Unknown SCB table_id: {table_id}")

    fetcher = ScbFetcher()
    db = Session()
    try:
        with pipeline_run(db, f"scb_{table_id.replace('/', '_')}") as ctx:
            # Ensure series row exists
            db.execute(
                text("""
                    INSERT INTO norric_scb_series (table_id, title_sv, description, cadence)
                    VALUES (:tid, :title, :desc, :cadence)
                    ON CONFLICT (table_id) DO UPDATE SET last_fetched_at = now()
                """),
                {
                    "tid":    config["table_id"],
                    "title":  config["title_sv"],
                    "desc":   config.get("description"),
                    "cadence": config["cadence"],
                },
            )
            db.commit()

            obs = fetcher.fetch_table(table_id, config["query_spec"])
            stats = _upsert_observations(db, obs)
            ctx["rows_processed"] = len(obs)
            ctx["rows_inserted"]  = stats["inserted"]
            ctx["rows_skipped"]   = stats["skipped"]
            log.info("SCB %s: %s", table_id, stats)
            return stats
    finally:
        db.close()


@shared_task(name="scb.ingest_all_tables")
def scb_ingest_all():
    """Ingest all configured SCB tables."""
    results = {}
    for config in SCB_TABLES:
        try:
            results[config["table_id"]] = scb_ingest_table(config["table_id"])
        except Exception as exc:
            log.error("SCB table %s failed: %s", config["table_id"], exc)
            results[config["table_id"]] = {"error": str(exc)}
    return results
