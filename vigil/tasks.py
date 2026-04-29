"""
vigil/tasks.py

Vigil lifecycle signal pipelines — three sources:

  Source 1: F-skatt registration (business birth)
    - Reads norric_entities where orgform is active + cross-refs vigil_fskatt_registrations
    - Emits: event_type=f_skatt_registration

  Source 2: Building permit intelligence (expansion)
    - Reads Malmö open data API (plan.malmo.se/datasets)
    - Emits: event_type=building_permit

  Source 3: Bolagsverket ownership velocity (transition)
    - Reads norric_entity_snapshots for ownership change diffs (aggregate count — no names)
    - Emits: event_type=ownership_change

All events written to vigil_events. company_profiles updated with correlated_signals
when an entity fires 2+ signals within 90 days.
"""

import logging
import os
from datetime import datetime, date, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy import text

log = logging.getLogger(__name__)


def _get_db():
    from ingestion.db import Session
    return Session()


# ── Source 1: F-skatt registration ────────────────────────────────────────────

def detect_fskatt_registrations(kommunkod: Optional[str] = None) -> dict:
    """
    Detect newly active F-skatt companies by cross-referencing norric_entities
    with vigil_fskatt_registrations.

    Only entities not yet in vigil_fskatt_registrations are considered new.
    Emits one vigil_events row per new detection.
    """
    db = _get_db()
    try:
        # Find active entities not yet tracked as F-skatt registrations
        where = "ne.is_active = true AND ne.orgform IN ('AB', 'HB', 'EF', 'KB')"
        params = {}
        if kommunkod:
            where += " AND ne.kommunkod = :kommunkod"
            params["kommunkod"] = kommunkod

        rows = db.execute(
            text(f"""
                SELECT ne.orgnr, ne.name, ne.kommunkod, ne.first_seen_at, ne.city
                FROM norric_entities ne
                WHERE {where}
                  AND NOT EXISTS (
                      SELECT 1 FROM vigil_fskatt_registrations vf
                      WHERE vf.orgnr = ne.orgnr
                  )
                LIMIT 500
            """),
            params,
        ).fetchall()

        detected = 0
        for row in rows:
            orgnr = row.orgnr
            try:
                # Insert into fskatt tracking
                db.execute(
                    text("""
                        INSERT INTO vigil_fskatt_registrations (orgnr, approved_at, detected_at)
                        VALUES (:orgnr, :approved_at, now())
                        ON CONFLICT (orgnr) DO NOTHING
                    """),
                    {
                        "orgnr": orgnr,
                        "approved_at": row.first_seen_at.date() if row.first_seen_at else None,
                    },
                )

                # Emit vigil event
                db.execute(
                    text("""
                        INSERT INTO vigil_events (orgnr, event_type, source, detected_at, payload, tier_required)
                        VALUES (:orgnr, 'f_skatt_registration', 'skatteverket', now(), :payload::jsonb, 1)
                    """),
                    {
                        "orgnr": orgnr,
                        "payload": _json({"kommunkod": row.kommunkod, "city": row.city}),
                    },
                )

                # Upsert company_profile
                _upsert_profile(db, orgnr, {
                    "lifecycle_stage": "new_business",
                    "f_skatt_active_at": row.first_seen_at.date() if row.first_seen_at else None,
                    "vigil_detected_at": datetime.now(timezone.utc),
                })

                detected += 1

            except Exception as e:
                log.error(f"[{orgnr}] F-skatt detection error: {e}", exc_info=True)

        db.commit()
        _run_correlation_check(db)
        return {"detected": detected, "checked": len(rows), "source": "f_skatt"}

    except Exception as e:
        db.rollback()
        log.error(f"detect_fskatt_registrations failed: {e}", exc_info=True)
        raise
    finally:
        db.close()


# ── Source 2: Building permits (Malmö open data) ───────────────────────────────

MALMO_BYGGLOV_URL = "https://opendata.malmo.se/explore/dataset/malmo_stadsarkivet_bygglov/api/"

def detect_building_permits(days_back: int = 7) -> dict:
    """
    Fetch building permits from Malmö open data API.
    Writes new permits to vigil_building_permits + emits vigil_events.

    Falls back gracefully if API is unavailable.
    """
    db = _get_db()
    try:
        since = (date.today() - timedelta(days=days_back)).isoformat()
        params = {
            "where": f"datumformansokan >= '{since}'",
            "limit": 100,
            "timezone": "Europe/Stockholm",
        }

        try:
            resp = httpx.get(MALMO_BYGGLOV_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except httpx.RequestError as e:
            log.warning(f"Malmö bygglov API unavailable: {e} — skipping")
            return {"detected": 0, "source": "malmo_open_data", "status": "api_unavailable"}
        except httpx.HTTPStatusError as e:
            log.warning(f"Malmö bygglov API error {e.response.status_code} — skipping")
            return {"detected": 0, "source": "malmo_open_data", "status": "api_error"}

        records = data.get("records", [])
        detected = 0

        for record in records:
            fields = record.get("fields", {})
            try:
                fastighet_id = fields.get("fastighetsbeteckning")
                permit_type = _normalise_permit_type(fields.get("typavlov", ""))
                status = _normalise_status(fields.get("status", ""))
                filed_at_str = fields.get("datumformansokan")
                filed_at = date.fromisoformat(filed_at_str) if filed_at_str else None
                address = fields.get("adress")

                db.execute(
                    text("""
                        INSERT INTO vigil_building_permits
                            (fastighet_id, permit_type, status, filed_at, address, municipality, raw_data, detected_at)
                        VALUES
                            (:fastighet_id, :permit_type, :status, :filed_at, :address, 'Malmö', :raw::jsonb, now())
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "fastighet_id": fastighet_id,
                        "permit_type": permit_type,
                        "status": status,
                        "filed_at": filed_at,
                        "address": address,
                        "raw": _json(fields),
                    },
                )

                db.execute(
                    text("""
                        INSERT INTO vigil_events
                            (fastighet_id, event_type, source, detected_at, payload, tier_required)
                        VALUES
                            (:fastighet_id, 'building_permit', 'malmo_open_data', now(), :payload::jsonb, 2)
                    """),
                    {
                        "fastighet_id": fastighet_id,
                        "payload": _json({
                            "permit_type": permit_type,
                            "status": status,
                            "address": address,
                            "filed_at": str(filed_at) if filed_at else None,
                        }),
                    },
                )
                detected += 1

            except Exception as e:
                log.error(f"Building permit record error: {e}", exc_info=True)

        db.commit()
        return {"detected": detected, "source": "malmo_open_data", "status": "ok"}

    except Exception as e:
        db.rollback()
        log.error(f"detect_building_permits failed: {e}", exc_info=True)
        raise
    finally:
        db.close()


# ── Source 3: Ownership change velocity ───────────────────────────────────────

def detect_ownership_changes() -> dict:
    """
    Scan norric_entity_snapshots for ownership-related changes.
    Counts changes per entity — NEVER stores individual names.
    Updates company_profiles.ownership_changes_12m.
    """
    db = _get_db()
    try:
        # Look for snapshots that contain ownership-related diff fields
        rows = db.execute(
            text("""
                SELECT
                    orgnr,
                    COUNT(*) AS change_count,
                    MAX(captured_at) AS latest_change
                FROM norric_entity_snapshots
                WHERE captured_at >= now() - interval '12 months'
                  AND diff IS NOT NULL
                  AND (
                      diff ? 'styrelse' OR
                      diff ? 'firmatecknare' OR
                      diff ? 'aktieagare'
                  )
                GROUP BY orgnr
                HAVING COUNT(*) >= 1
            """)
        ).fetchall()

        updated = 0
        for row in rows:
            orgnr = row.orgnr
            change_count = int(row.change_count)
            latest = row.latest_change

            try:
                _upsert_profile(db, orgnr, {
                    "ownership_changes_12m": change_count,
                    "ownership_last_change_at": latest.date() if latest else None,
                    "lifecycle_stage": "transitioning" if change_count >= 3 else None,
                })

                if change_count >= 2:
                    db.execute(
                        text("""
                            INSERT INTO vigil_events
                                (orgnr, event_type, source, detected_at, payload, tier_required)
                            VALUES
                                (:orgnr, 'ownership_change', 'bolagsverket', now(), :payload::jsonb, 3)
                        """),
                        {
                            "orgnr": orgnr,
                            "payload": _json({
                                "change_count_12m": change_count,
                                "latest_change": str(latest.date()) if latest else None,
                            }),
                        },
                    )
                    updated += 1

            except Exception as e:
                log.error(f"[{orgnr}] ownership change error: {e}", exc_info=True)

        db.commit()
        _run_correlation_check(db)
        return {"updated": updated, "checked": len(rows), "source": "bolagsverket_snapshots"}

    except Exception as e:
        db.rollback()
        log.error(f"detect_ownership_changes failed: {e}", exc_info=True)
        raise
    finally:
        db.close()


# ── Cross-signal correlation ───────────────────────────────────────────────────

def _run_correlation_check(db) -> None:
    """
    Populate correlated_signals on company_profiles when an entity fires
    2+ event types within 90 days. Foundation for Tier 3 correlation engine.
    """
    import json

    rows = db.execute(
        text("""
            SELECT
                orgnr,
                array_agg(DISTINCT event_type) AS event_types,
                MIN(detected_at) AS first_seen,
                MAX(detected_at) AS last_seen
            FROM vigil_events
            WHERE orgnr IS NOT NULL
              AND detected_at >= now() - interval '90 days'
            GROUP BY orgnr
            HAVING COUNT(DISTINCT event_type) >= 2
        """)
    ).fetchall()

    for row in rows:
        orgnr = row.orgnr
        event_types = list(row.event_types)

        correlation = {
            "event_types": event_types,
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            "correlation_confidence": min(0.95, 0.5 + len(event_types) * 0.15),
            "interpretation": _interpret_correlation(event_types),
        }

        db.execute(
            text("""
                INSERT INTO company_profiles (orgnr, correlated_signals, last_correlated_at)
                VALUES (:orgnr, :signals::jsonb, now())
                ON CONFLICT (orgnr) DO UPDATE SET
                    correlated_signals   = EXCLUDED.correlated_signals,
                    last_correlated_at   = EXCLUDED.last_correlated_at,
                    updated_at           = now()
            """),
            {"orgnr": orgnr, "signals": json.dumps(correlation)},
        )

    if rows:
        db.commit()
        log.info(f"Correlation: updated {len(rows)} company profiles")


def _interpret_correlation(event_types: list) -> str:
    types = set(event_types)
    if "f_skatt_registration" in types and "building_permit" in types:
        return "new_business_expanding"
    if "f_skatt_registration" in types and "ownership_change" in types:
        return "new_business_restructuring"
    if "ownership_change" in types and "building_permit" in types:
        return "expansion_with_ownership_change"
    return "multi_signal_activity"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _upsert_profile(db, orgnr: str, fields: dict) -> None:
    """Upsert company_profiles for an orgnr with given non-None fields."""
    set_clauses = []
    params = {"orgnr": orgnr}

    if "lifecycle_stage" in fields and fields["lifecycle_stage"]:
        set_clauses.append("lifecycle_stage = :lifecycle_stage")
        params["lifecycle_stage"] = fields["lifecycle_stage"]
    if "f_skatt_active_at" in fields and fields["f_skatt_active_at"]:
        set_clauses.append("f_skatt_active_at = :f_skatt_active_at")
        params["f_skatt_active_at"] = fields["f_skatt_active_at"]
    if "vigil_detected_at" in fields:
        set_clauses.append("vigil_detected_at = :vigil_detected_at")
        params["vigil_detected_at"] = fields["vigil_detected_at"]
    if "ownership_changes_12m" in fields:
        set_clauses.append("ownership_changes_12m = :ownership_changes_12m")
        params["ownership_changes_12m"] = fields["ownership_changes_12m"]
    if "ownership_last_change_at" in fields and fields["ownership_last_change_at"]:
        set_clauses.append("ownership_last_change_at = :ownership_last_change_at")
        params["ownership_last_change_at"] = fields["ownership_last_change_at"]

    if not set_clauses:
        return

    set_clause = ", ".join(set_clauses) + ", updated_at = now()"

    db.execute(
        text(f"""
            INSERT INTO company_profiles (orgnr, {", ".join(f.split(' = ')[0] for f in set_clauses)})
            VALUES (:orgnr, {", ".join(f":{f.split(' = ')[0].strip()}" for f in set_clauses)})
            ON CONFLICT (orgnr) DO UPDATE SET {set_clause}
        """),
        params,
    )


def _normalise_permit_type(raw: str) -> str:
    r = raw.lower()
    if "nybygg" in r:
        return "nybyggnad"
    if "tillbygg" in r:
        return "tillbyggnad"
    if "ombygg" in r or "ändring" in r:
        return "ombyggnad"
    return raw or "okänd"


def _normalise_status(raw: str) -> str:
    r = raw.lower()
    if "beviljat" in r or "godkänd" in r:
        return "beviljat"
    if "avsla" in r or "avslagit" in r:
        return "avslagat"
    if "ansökt" in r or "inkomm" in r:
        return "ansökt"
    return raw or "okänd"


def _json(d: dict) -> str:
    import json
    return json.dumps(d, default=str)


# ── Celery task registration ───────────────────────────────────────────────────

def register_tasks(celery_app):
    @celery_app.task(name="vigil.tasks.detect_fskatt_registrations", bind=True, max_retries=2)
    def _fskatt_task(self, kommunkod=None):
        try:
            return detect_fskatt_registrations(kommunkod)
        except Exception as exc:
            log.error(f"detect_fskatt_registrations failed: {exc}")
            raise self.retry(exc=exc)

    @celery_app.task(name="vigil.tasks.detect_building_permits", bind=True, max_retries=2)
    def _permits_task(self, days_back=7):
        try:
            return detect_building_permits(days_back)
        except Exception as exc:
            log.error(f"detect_building_permits failed: {exc}")
            raise self.retry(exc=exc)

    @celery_app.task(name="vigil.tasks.detect_ownership_changes", bind=True, max_retries=2)
    def _ownership_task(self):
        try:
            return detect_ownership_changes()
        except Exception as exc:
            log.error(f"detect_ownership_changes failed: {exc}")
            raise self.retry(exc=exc)

    return _fskatt_task, _permits_task, _ownership_task
