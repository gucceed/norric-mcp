-- T2_006: Query log for quota tracking and privacy-safe analytics
-- ip_hash: SHA-256 of raw IP, no plaintext IPs stored
-- No endpoint exposes user-level query history except the user's own session

CREATE TABLE IF NOT EXISTS query_log (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    queried_org_nr  text NOT NULL,
    queried_at      timestamptz NOT NULL DEFAULT now(),
    tier_at_query   user_tier NOT NULL,
    ip_hash         text NOT NULL
);

-- Primary quota index: count lookups per user per month
CREATE INDEX IF NOT EXISTS idx_query_log_user_month
    ON query_log(user_id, queried_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_log_queried_at
    ON query_log(queried_at DESC);

-- Sector-level interest view (aggregate only — no user-level exposure)
-- Returns lookup counts per org_nr sector prefix, not per user
CREATE OR REPLACE VIEW sector_interest_counts AS
SELECT
    LEFT(queried_org_nr, 2) AS sector_prefix,
    DATE_TRUNC('month', queried_at) AS month,
    COUNT(*) AS lookup_count
FROM query_log
GROUP BY 1, 2;
