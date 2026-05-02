-- T2_008: Monthly quota tracking for Free-tier API keys
-- key_hash matches the SHA-256 stored in NORRIC_API_KEYS env var
-- Resets on the 1st of each month at 00:00 UTC

CREATE TABLE IF NOT EXISTS quota_usage (
    key_hash      text         PRIMARY KEY,
    call_count    int          NOT NULL DEFAULT 0,
    period_start  timestamptz  NOT NULL,
    reset_at      timestamptz  NOT NULL
);

-- Verification: SELECT count(*) FROM quota_usage;
