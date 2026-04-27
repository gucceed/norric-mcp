-- T1-08: Unified snapshot store + temporal views

CREATE TABLE IF NOT EXISTS norric_snapshots (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       text NOT NULL,
    entity_type     text NOT NULL,
    source          text NOT NULL,
    pipeline_run_id uuid REFERENCES norric_pipeline_runs(id),
    snapshot_date   date NOT NULL,
    data            jsonb NOT NULL,
    diff_from_prev  jsonb,
    checksum        text NOT NULL,
    created_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_entity_date
    ON norric_snapshots(entity_id, source, snapshot_date DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_dedup
    ON norric_snapshots(entity_id, source, snapshot_date, checksum);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON norric_snapshots(snapshot_date DESC);

-- Temporal views for Tier 5 sensors

CREATE OR REPLACE VIEW norric_entity_at_date AS
SELECT DISTINCT ON (entity_id, source, snapshot_date)
    entity_id, entity_type, source, snapshot_date, data, diff_from_prev
FROM norric_snapshots
ORDER BY entity_id, source, snapshot_date DESC;

CREATE OR REPLACE VIEW norric_field_changes AS
SELECT
    entity_id,
    entity_type,
    source,
    snapshot_date,
    key  AS field_name,
    (value->>'from') AS old_value,
    (value->>'to')   AS new_value
FROM norric_snapshots,
     jsonb_each(diff_from_prev)
WHERE diff_from_prev IS NOT NULL;

CREATE OR REPLACE VIEW norric_entity_velocity_30d AS
SELECT
    entity_id,
    entity_type,
    source,
    COUNT(*)                         AS change_events,
    array_agg(DISTINCT field_name)   AS changed_fields
FROM norric_field_changes
WHERE snapshot_date >= now()::date - 30
GROUP BY entity_id, entity_type, source;
