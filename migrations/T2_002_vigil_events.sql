-- T2-02: Vigil lifecycle event store

CREATE TABLE IF NOT EXISTS vigil_events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr           text,
    fastighet_id    text,
    event_type      text NOT NULL,          -- f_skatt_registration | building_permit | ownership_change
    detected_at     timestamptz NOT NULL DEFAULT now(),
    source          text NOT NULL,          -- skatteverket | bolagsverket | malmo_open_data
    payload         jsonb NOT NULL DEFAULT '{}',
    tier_required   int NOT NULL DEFAULT 2, -- 1=basic, 2=standard, 3=premium
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vigil_events_orgnr
    ON vigil_events(orgnr);
CREATE INDEX IF NOT EXISTS idx_vigil_events_type
    ON vigil_events(event_type, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_vigil_events_detected
    ON vigil_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_vigil_events_fastighet
    ON vigil_events(fastighet_id) WHERE fastighet_id IS NOT NULL;

-- F-skatt registrations (Vigil source 1)
CREATE TABLE IF NOT EXISTS vigil_fskatt_registrations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr           text NOT NULL UNIQUE,
    approved_at     date,
    revoked_at      date,
    is_active       boolean NOT NULL DEFAULT true,
    detected_at     timestamptz NOT NULL DEFAULT now(),
    source_run_id   uuid REFERENCES norric_pipeline_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_fskatt_orgnr
    ON vigil_fskatt_registrations(orgnr);
CREATE INDEX IF NOT EXISTS idx_fskatt_approved
    ON vigil_fskatt_registrations(approved_at DESC);

-- Building permits (Vigil source 2 — Malmö open data first)
CREATE TABLE IF NOT EXISTS vigil_building_permits (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fastighet_id    text,
    orgnr           text,                   -- resolved from address if possible
    permit_type     text,                   -- nybyggnad | tillbyggnad | ombyggnad
    status          text,                   -- ansökt | beviljat | avslagat
    filed_at        date,
    decided_at      date,
    address         text,
    municipality    text,
    raw_data        jsonb,
    detected_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_permits_fastighet
    ON vigil_building_permits(fastighet_id);
CREATE INDEX IF NOT EXISTS idx_permits_orgnr
    ON vigil_building_permits(orgnr) WHERE orgnr IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_permits_filed
    ON vigil_building_permits(filed_at DESC);
