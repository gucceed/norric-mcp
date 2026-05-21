"""
kreditvakt/contagion.py

Supply-chain contagion engine for HIGH and CRITICAL companies.

  compute_contagion_peers(orgnr, tier, db, limit)  — derive peers for one source
  get_cached_contagion_peers(orgnr, db, limit)     — read-only cache lookup
  refresh_contagion_peers()                         — Celery task; refresh all HIGH/CRITICAL

Match key pivot (decided 2026-05-21):
  norric_entities has no sni_code column. We derive each supplier's sector
  from their most-frequent signal_contracts.sector and match peers on
  (sector, kommunkod) → (sector, county) as fallback. Companies that have
  never appeared in procurement have no derivable sector and yield 0 peers.

Probabilistic, not verified. These are LIKELY relationships based on
shared procurement sector + geography, not confirmed supply chain
transactions. Always frame with disclaimer in surfaced responses.
"""

import logging
from typing import Optional

from celery import shared_task
from sqlalchemy import text

from ingestion.db import Session

log = logging.getLogger(__name__)


# Canonical band → tier map (matches scoring.kreditvakt.TIER_FROM_BAND).
TIER_FROM_BAND = {1: "HEALTHY", 2: "WATCH", 3: "ELEVATED", 4: "HIGH", 5: "CRITICAL"}

# Canonical 1–5 band → 0–20 risk_score midpoints (matches
# scoring.kreditvakt._risk_score_from_band).
SCORE_FROM_BAND = {1: 2, 2: 6, 3: 10, 4: 14, 5: 18}

# Source qualifies for contagion analysis only at HIGH (band 4) or CRITICAL (band 5).
CONTAGION_BANDS = (4, 5)

# Proximity scores by match reason. Higher = tighter relationship.
PROXIMITY = {
    "same_sector_kommunkod": 1.0,
    "same_sector_county":    0.7,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _derive_supplier_sector(db, orgnr: str) -> Optional[str]:
    """Return the most-frequent signal_contracts.sector for this supplier, or None.

    Companies that have never appeared as a supplier in any scraped
    procurement contract yield None — contagion is undefined for them.
    """
    row = db.execute(text("""
        SELECT sector, COUNT(*) AS freq
        FROM signal_contracts
        WHERE supplier_orgnr = :orgnr
          AND sector IS NOT NULL
        GROUP BY sector
        ORDER BY freq DESC
        LIMIT 1
    """), {"orgnr": orgnr}).fetchone()
    return row.sector if row else None


def _lookup_source_geography(db, orgnr: str) -> Optional[tuple]:
    """Return (kommunkod, county) for the source orgnr from norric_entities.

    Matches against orgnr_display (dashed) — the same lookup convention as
    kreditvakt/api.py:354.
    """
    row = db.execute(text("""
        SELECT kommunkod, county
        FROM norric_entities
        WHERE orgnr_display = :orgnr
        LIMIT 1
    """), {"orgnr": orgnr}).fetchone()
    if row is None:
        return None
    return (row.kommunkod, row.county)


def _peers_in_same_kommunkod(
    db, source_orgnr: str, sector: str, kommunkod: str, limit: int
) -> list[dict]:
    """Find peers in the same sector + same kommunkod (highest proximity)."""
    if not kommunkod:
        return []
    rows = db.execute(text("""
        SELECT
            ne.orgnr_display AS orgnr,
            ne.name,
            cs.risk_band
        FROM norric_entities ne
        JOIN company_scores cs ON cs.orgnr = ne.orgnr_display
        WHERE ne.kommunkod = :kommunkod
          AND ne.orgnr_display != :source_orgnr
          AND cs.updated_at > now() - INTERVAL '30 days'
          AND EXISTS (
              SELECT 1 FROM signal_contracts sc
              WHERE sc.supplier_orgnr = ne.orgnr_display
                AND sc.sector = :sector
          )
        ORDER BY cs.risk_band DESC, cs.distress_probability DESC
        LIMIT :limit
    """), {
        "kommunkod":    kommunkod,
        "source_orgnr": source_orgnr,
        "sector":       sector,
        "limit":        limit,
    }).fetchall()
    return [_row_to_peer(r, "same_sector_kommunkod") for r in rows]


def _peers_in_same_county(
    db, source_orgnr: str, sector: str, county: str, kommunkod: str,
    exclude_orgnrs: list[str], limit: int,
) -> list[dict]:
    """Expand to same sector + same county, excluding kommunkod hits already returned."""
    if not county:
        return []
    rows = db.execute(text("""
        SELECT
            ne.orgnr_display AS orgnr,
            ne.name,
            cs.risk_band
        FROM norric_entities ne
        JOIN company_scores cs ON cs.orgnr = ne.orgnr_display
        WHERE ne.county = :county
          AND (ne.kommunkod IS NULL OR ne.kommunkod != :kommunkod)
          AND ne.orgnr_display != :source_orgnr
          AND ne.orgnr_display != ALL(:exclude)
          AND cs.updated_at > now() - INTERVAL '30 days'
          AND EXISTS (
              SELECT 1 FROM signal_contracts sc
              WHERE sc.supplier_orgnr = ne.orgnr_display
                AND sc.sector = :sector
          )
        ORDER BY cs.risk_band DESC, cs.distress_probability DESC
        LIMIT :limit
    """), {
        "county":       county,
        "kommunkod":    kommunkod or "",
        "source_orgnr": source_orgnr,
        "exclude":      exclude_orgnrs or [""],
        "sector":       sector,
        "limit":        limit,
    }).fetchall()
    return [_row_to_peer(r, "same_sector_county") for r in rows]


def _row_to_peer(row, match_reason: str) -> dict:
    band = int(row.risk_band) if row.risk_band is not None else None
    return {
        "orgnr":           row.orgnr,
        "name":            row.name,
        "tier":            TIER_FROM_BAND.get(band) if band is not None else None,
        "kv_score":        SCORE_FROM_BAND.get(band) if band is not None else None,
        "match_reason":    match_reason,
        "proximity_score": PROXIMITY[match_reason],
    }


# ── Public: compute (no DB writes) ────────────────────────────────────────────

def compute_contagion_peers(
    orgnr: str,
    tier: str,
    db,
    limit: int = 10,
    county_expand_threshold: int = 5,
) -> list[dict]:
    """For a HIGH or CRITICAL company, find likely supply-chain peers.

    Method (Option A pivot, sector-via-contracts):
      1. Derive source's sector from the most-frequent sector across their
         signal_contracts rows. If none — return [].
      2. Look up source's kommunkod + county from norric_entities. If neither
         is set — return [].
      3. Find peers in same sector + same kommunkod (proximity 1.0).
      4. If fewer than `county_expand_threshold` results, top up with peers
         in same sector + same county, excluding kommunkod hits (proximity 0.7).

    Returns up to `limit` peer dicts:
        {orgnr, name, tier, kv_score, match_reason, proximity_score}

    Probabilistic — these are likely relationships, not verified supply
    chains. Surface the disclaimer in every response built from this output.
    """
    sector = _derive_supplier_sector(db, orgnr)
    if not sector:
        log.info("contagion: %s — no derivable sector (no procurement history)", orgnr)
        return []

    geo = _lookup_source_geography(db, orgnr)
    if geo is None:
        log.info("contagion: %s — not in norric_entities", orgnr)
        return []
    kommunkod, county = geo
    if not kommunkod and not county:
        log.info("contagion: %s — no geography on norric_entities", orgnr)
        return []

    primary = _peers_in_same_kommunkod(db, orgnr, sector, kommunkod, limit)

    if len(primary) < county_expand_threshold and county:
        remaining = limit - len(primary)
        expand = _peers_in_same_county(
            db, orgnr, sector, county, kommunkod,
            [p["orgnr"] for p in primary],
            remaining,
        )
        return primary + expand

    return primary


# ── Public: read-only cache lookup ────────────────────────────────────────────

def get_cached_contagion_peers(orgnr: str, db, limit: int = 5) -> list[dict]:
    """Read valid (non-expired) cached peers for a source orgnr.

    Returns [] on cache miss — does NOT trigger compute. Safe to call from
    the score response path; never blocks scoring.
    """
    rows = db.execute(text("""
        SELECT peer_orgnr, peer_name, peer_tier, peer_kv_score,
               match_reason, proximity_score
        FROM contagion_peers
        WHERE source_orgnr = :orgnr
          AND valid_until > now()
        ORDER BY proximity_score DESC, peer_kv_score DESC NULLS LAST
        LIMIT :limit
    """), {"orgnr": orgnr, "limit": limit}).fetchall()
    return [
        {
            "orgnr":           r.peer_orgnr,
            "name":            r.peer_name,
            "tier":            r.peer_tier,
            "kv_score":        r.peer_kv_score,
            "match_reason":    r.match_reason,
            "proximity_score": r.proximity_score,
        }
        for r in rows
    ]


# ── Persist (private — used by refresh task and the MCP tool's compute path) ──

def persist_contagion_peers(
    db, source_orgnr: str, source_tier: str, peers: list[dict],
    valid_for_hours: int = 24,
) -> int:
    """Replace cache rows for a source. Returns number of rows persisted.

    Strategy: delete existing rows for this source, then bulk insert. UNIQUE
    constraint on (source_orgnr, peer_orgnr) would also let us upsert, but
    delete-then-insert is cleaner when peer set shrinks between refreshes.
    """
    db.execute(text("""
        DELETE FROM contagion_peers WHERE source_orgnr = :orgnr
    """), {"orgnr": source_orgnr})

    if not peers:
        return 0

    db.execute(text(f"""
        INSERT INTO contagion_peers (
            source_orgnr, source_tier,
            peer_orgnr, peer_name, peer_tier, peer_kv_score,
            match_reason, proximity_score,
            valid_until
        )
        VALUES (
            :source_orgnr, :source_tier,
            :peer_orgnr, :peer_name, :peer_tier, :peer_kv_score,
            :match_reason, :proximity_score,
            now() + INTERVAL '{int(valid_for_hours)} hours'
        )
        ON CONFLICT (source_orgnr, peer_orgnr) DO NOTHING
    """), [
        {
            "source_orgnr":    source_orgnr,
            "source_tier":     source_tier,
            "peer_orgnr":      p["orgnr"],
            "peer_name":       p["name"],
            "peer_tier":       p["tier"],
            "peer_kv_score":   p["kv_score"],
            "match_reason":    p["match_reason"],
            "proximity_score": p["proximity_score"],
        }
        for p in peers
    ])
    return len(peers)


# ── Celery task: refresh all HIGH/CRITICAL ────────────────────────────────────

@shared_task(
    name="signal.refresh_contagion",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def refresh_contagion_peers(self) -> dict:
    """Refresh contagion peers for all HIGH and CRITICAL companies.

    Beat cadence: every 4 hours (see celeryconfig.beat_schedule). Deletes
    expired cache rows first, then re-computes any HIGH/CRITICAL source
    that lacks a valid cache entry. Bounded by LIMIT 500 per run to keep
    individual task duration manageable.
    """
    log.info("signal.refresh_contagion: starting")

    refreshed = 0
    deleted_expired = 0
    no_sector = 0
    errors = 0

    db = Session()
    try:
        # 1. Delete expired cache rows
        result = db.execute(text("""
            DELETE FROM contagion_peers WHERE valid_until <= now()
        """))
        deleted_expired = result.rowcount or 0
        db.commit()
        log.info("signal.refresh_contagion: deleted %d expired rows", deleted_expired)

        # 2. Find HIGH/CRITICAL companies without a valid cache entry.
        # company_scores.orgnr is UNIQUE (T2_001 idx_company_scores_orgnr),
        # so no DISTINCT needed.
        rows = db.execute(text("""
            SELECT cs.orgnr,
                CASE WHEN cs.risk_band >= 5 THEN 'CRITICAL'
                     WHEN cs.risk_band >= 4 THEN 'HIGH'
                END AS tier
            FROM company_scores cs
            WHERE cs.risk_band >= 4
              AND NOT EXISTS (
                  SELECT 1 FROM contagion_peers cp
                  WHERE cp.source_orgnr = cs.orgnr
                    AND cp.valid_until > now()
              )
            ORDER BY cs.risk_band DESC
            LIMIT 500
        """)).fetchall()

        log.info("signal.refresh_contagion: %d HIGH/CRITICAL companies need refresh", len(rows))

        for row in rows:
            try:
                peers = compute_contagion_peers(row.orgnr, row.tier, db, limit=10)
                if not peers:
                    no_sector += 1
                    # Persist nothing — source will be reconsidered next run.
                    continue
                persist_contagion_peers(db, row.orgnr, row.tier, peers)
                db.commit()
                refreshed += 1
            except Exception as exc:
                db.rollback()
                log.warning(
                    "signal.refresh_contagion: source %s failed: %s",
                    row.orgnr, exc,
                )
                errors += 1
                continue
    except Exception as exc:
        log.error("signal.refresh_contagion: DB failure: %s", exc, exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        log.error("signal.refresh_contagion: retries exhausted, returning partial")
    finally:
        db.close()

    log.info(
        "signal.refresh_contagion: done refreshed=%d deleted_expired=%d "
        "no_sector=%d errors=%d",
        refreshed, deleted_expired, no_sector, errors,
    )
    return {
        "refreshed":       refreshed,
        "deleted_expired": deleted_expired,
        "no_sector":       no_sector,
        "errors":          errors,
    }
