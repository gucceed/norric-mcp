-- ============================================================
-- SIGNAL_003_contagion_cache.sql
-- Supply chain contagion cache
--
-- Pre-computed contagion peers for HIGH and CRITICAL companies.
-- Populated by kreditvakt.contagion.refresh_contagion_peers
-- (Celery, every 4h). Read by kreditvakt_contagion_v1 MCP tool
-- and surfaced as contagion_preview in kreditvakt_score_company_v1.
--
-- Match key pivot (decided 2026-05-21): norric_entities has no
-- sni_code / municipality columns. We derive each supplier's
-- sector from their most frequent signal_contracts.sector and
-- match peers on (sector, kommunkod) → (sector, county) fallback.
-- See kreditvakt/contagion.py for full method.
-- ============================================================

CREATE TABLE IF NOT EXISTS contagion_peers (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The HIGH or CRITICAL company that triggered the analysis
    source_orgnr    VARCHAR(20)  NOT NULL,
    source_tier     VARCHAR(20)  NOT NULL,   -- canonical: HIGH | CRITICAL

    -- The peer company identified as potentially exposed
    peer_orgnr      VARCHAR(20)  NOT NULL,
    peer_name       TEXT,
    peer_tier       VARCHAR(20),             -- canonical: HEALTHY..CRITICAL
    peer_kv_score   SMALLINT,                -- 0–20 ascending

    -- Why this peer was identified
    match_reason    TEXT         NOT NULL,
    --   same_sector_kommunkod  (proximity 1.0)
    --   same_sector_county     (proximity 0.7)
    proximity_score FLOAT,

    -- State
    computed_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    valid_until     TIMESTAMPTZ  NOT NULL DEFAULT now() + INTERVAL '24 hours',

    UNIQUE (source_orgnr, peer_orgnr)
);

CREATE INDEX IF NOT EXISTS ix_cp_source_orgnr ON contagion_peers(source_orgnr);
CREATE INDEX IF NOT EXISTS ix_cp_peer_orgnr   ON contagion_peers(peer_orgnr);
CREATE INDEX IF NOT EXISTS ix_cp_valid        ON contagion_peers(valid_until);
CREATE INDEX IF NOT EXISTS ix_cp_source_tier  ON contagion_peers(source_tier);

COMMENT ON TABLE contagion_peers IS
'Supply chain contagion cache. Probabilistic peer relationships derived from '
'shared sector (via signal_contracts) and geographic proximity (kommunkod/county). '
'NOT verified supply chain transactions. Refresh cadence: 4h via Celery Beat.';
