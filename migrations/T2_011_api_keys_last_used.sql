-- T2_011: add last_used_at to api_keys for usage tracking
ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS last_used_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
