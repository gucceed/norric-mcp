-- T1-04: SCB statistics tables

CREATE TABLE IF NOT EXISTS norric_scb_series (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id        text NOT NULL UNIQUE,
    title_sv        text NOT NULL,
    description     text,
    cadence         text NOT NULL,
    last_fetched_at timestamptz,
    created_at      timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS norric_scb_observations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id        text NOT NULL REFERENCES norric_scb_series(table_id),
    period          text NOT NULL,
    region_kod      text,
    dimension_key   text NOT NULL,
    dimension_val   text NOT NULL,
    value           numeric,
    unit            text,
    created_at      timestamptz DEFAULT now(),
    UNIQUE(table_id, period, region_kod, dimension_key, dimension_val)
);

CREATE INDEX IF NOT EXISTS idx_scb_obs_table  ON norric_scb_observations(table_id);
CREATE INDEX IF NOT EXISTS idx_scb_obs_period ON norric_scb_observations(period DESC);
CREATE INDEX IF NOT EXISTS idx_scb_obs_region ON norric_scb_observations(region_kod);
