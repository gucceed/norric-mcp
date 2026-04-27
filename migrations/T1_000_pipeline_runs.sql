-- T1-00: Pipeline run telemetry table
-- All other T1 pipelines reference this via source_run_id FK.
-- Must be created before any other T1 migration.

CREATE TABLE IF NOT EXISTS norric_pipeline_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline        text NOT NULL,          -- e.g. 'bolagsverket_bulk', 'kronofogden'
    started_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz,
    rows_processed  bigint DEFAULT 0,
    rows_inserted   bigint DEFAULT 0,
    rows_updated    bigint DEFAULT 0,
    rows_skipped    bigint DEFAULT 0,
    error_message   text,
    status          text NOT NULL DEFAULT 'running',  -- 'running' | 'success' | 'failed'
    meta            jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline ON norric_pipeline_runs(pipeline);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started  ON norric_pipeline_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status   ON norric_pipeline_runs(pipeline, status, started_at DESC);
