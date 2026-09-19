-- T5_001: Compounding core Stage 0 schema contract.
--
-- This migration is review-only in Stage 0. Do not apply before an explicit
-- production migration approval and a Stockholm rehearsal.

CREATE TABLE IF NOT EXISTS entity_events (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_ref           text NOT NULL UNIQUE,
    entity_key          text NOT NULL,
    entity_type         text NOT NULL,
    event_type          text NOT NULL CHECK (event_type IN (
        'entity.address.changed',
        'entity.officer.added',
        'entity.officer.removed',
        'entity.capital.changed',
        'entity.filing.added',
        'entity.bankruptcy.changed',
        'entity.score.changed',
        'entity.layoff_notice.changed'
    )),
    source              text NOT NULL CHECK (source IN (
        'bolagsverket_bulk',
        'bolagsverket_konkurs',
        'kreditvakt_scoring',
        'arbetsformedlingen_varsel'
    )),
    source_observed_at  timestamptz NOT NULL,
    detected_at         timestamptz NOT NULL,
    before_json         jsonb,
    after_json          jsonb,
    changed_fields      text[] NOT NULL CHECK (cardinality(changed_fields) > 0),
    evidence_json       jsonb NOT NULL,
    evidence_hash       text NOT NULL CHECK (length(evidence_hash) = 64),
    detector_version    text NOT NULL,
    idempotency_key     text NOT NULL UNIQUE CHECK (length(idempotency_key) = 64),
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (before_json IS DISTINCT FROM after_json)
);

CREATE INDEX IF NOT EXISTS idx_entity_events_entity_time
    ON entity_events(entity_key, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_type_time
    ON entity_events(event_type, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_source_observed
    ON entity_events(source, source_observed_at DESC);

-- Daily instrumentation is deliberately local to Supabase Stockholm. It lets
-- Norric enforce the approved cost stop-gate without adding analytics vendors.
CREATE TABLE IF NOT EXISTS entity_event_daily_metrics (
    metric_date         date NOT NULL,
    source              text NOT NULL,
    event_type          text NOT NULL,
    events_written      bigint NOT NULL DEFAULT 0,
    payload_bytes       bigint NOT NULL DEFAULT 0,
    beat_runtime_ms     bigint NOT NULL DEFAULT 0,
    deliveries_queued   bigint NOT NULL DEFAULT 0,
    measured_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (metric_date, source, event_type)
);
