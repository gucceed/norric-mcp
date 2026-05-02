-- T2_009: API key registry — persistent record of every issued key
-- key_hash is the SHA-256 of the raw nrk_ key (same format as NORRIC_API_KEYS env var)
-- org_nr is optional — populated for paid tiers collected at checkout

CREATE TABLE IF NOT EXISTS api_keys (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash    text        NOT NULL UNIQUE,
    tier        text        NOT NULL CHECK (tier IN ('free', 'standard', 'compliance')),
    org_nr      text,
    email       text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    status      text        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_api_keys_email  ON api_keys(email);
CREATE INDEX IF NOT EXISTS idx_api_keys_status ON api_keys(status);

-- Verification: SELECT column_name FROM information_schema.columns WHERE table_name='api_keys' ORDER BY ordinal_position;
