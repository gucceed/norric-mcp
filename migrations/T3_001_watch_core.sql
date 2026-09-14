-- T3_001: Norric Watch Phase 1 — change-detection webhooks (company watch core)
--
-- norric_watches       customer subscriptions (one row per watch, owned by api key)
-- norric_watch_events  one row per emitted event; doubles as the dead-letter
--                      store via status='dead' (retrievable 30 days, spec §6)
--
-- Event types in v1 all ride the live Kreditvakt beats (score diff, debt
-- signals, konkurs). Types whose pipelines are not live are rejected at the
-- API layer — see watch/validation.py.

CREATE TABLE IF NOT EXISTS norric_watches (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    watch_ref            text NOT NULL UNIQUE,          -- watch_<hex>, customer-facing id
    key_hash             text NOT NULL REFERENCES api_keys(key_hash),
    status               text NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active', 'paused')),
    event_types          text[] NOT NULL,
    filters              jsonb NOT NULL DEFAULT '{}',   -- {orgnrs: [...], min_score_delta: int}
    callback_url         text NOT NULL,                 -- https only; SSRF-checked at creation
    signing_secret       text NOT NULL,                 -- whsec_<hex>; shown once, never re-served
    description          text,
    events_sent          int  NOT NULL DEFAULT 0,
    last_delivery_at     timestamptz,
    consecutive_failures int  NOT NULL DEFAULT 0,       -- auto-pause at 50 (spec §6)
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_watches_key_hash ON norric_watches(key_hash);
CREATE INDEX IF NOT EXISTS idx_watches_status   ON norric_watches(status);

CREATE TABLE IF NOT EXISTS norric_watch_events (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_ref         text NOT NULL UNIQUE,             -- evt_<hex>; X-Norric-Event-Id
    watch_id          uuid NOT NULL REFERENCES norric_watches(id) ON DELETE CASCADE,
    event_type        text NOT NULL,
    orgnr             text,                             -- dashless 10-digit, canonical key form
    payload           jsonb NOT NULL,                   -- the exact signed body that was POSTed
    status            text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'delivered', 'dead')),
    attempts          int  NOT NULL DEFAULT 0,
    next_attempt_at   timestamptz NOT NULL DEFAULT now(),
    last_http_status  int,
    last_error        text,
    occurred_at       timestamptz NOT NULL,             -- when the change was detected
    delivered_at      timestamptz,
    dead_at           timestamptz,                      -- entered dead-letter after final retry
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_watch_events_watch    ON norric_watch_events(watch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_watch_events_orgnr    ON norric_watch_events(orgnr);
CREATE INDEX IF NOT EXISTS idx_watch_events_pending  ON norric_watch_events(next_attempt_at)
    WHERE status = 'pending';
-- Dead-letter retention view target: 30 days (spec §6)
CREATE INDEX IF NOT EXISTS idx_watch_events_dead     ON norric_watch_events(dead_at)
    WHERE status = 'dead';

-- Verification: SELECT column_name FROM information_schema.columns
--   WHERE table_name IN ('norric_watches','norric_watch_events')
--   ORDER BY table_name, ordinal_position;
