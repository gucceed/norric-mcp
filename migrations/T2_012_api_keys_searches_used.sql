-- T2_012: add lifetime search counter to api_keys
-- Separate from quota_usage (monthly, Silver+). This column tracks
-- lifetime Free-tier lookups with no reset logic.
ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS searches_used int NOT NULL DEFAULT 0;

-- Partial index: only Free keys ever hit the cap
CREATE INDEX IF NOT EXISTS idx_api_keys_free_searches
    ON api_keys (key_hash, searches_used)
    WHERE tier = 'free';
