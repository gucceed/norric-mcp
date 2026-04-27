-- T1-01: Bolagsverket entities + snapshots base tables

CREATE TABLE IF NOT EXISTS norric_entities (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr               text NOT NULL UNIQUE,
    orgnr_display       text NOT NULL,
    name                text NOT NULL,
    orgform             text NOT NULL,
    is_active           boolean NOT NULL DEFAULT true,
    deregistered_at     date,
    street              text,
    city                text,
    postcode            text,
    kommunkod           text,
    county              text,
    raw_address         text,
    source              text NOT NULL DEFAULT 'bolagsverket_bulk',
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    last_updated_at     timestamptz NOT NULL DEFAULT now(),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_entities_orgnr     ON norric_entities(orgnr);
CREATE INDEX IF NOT EXISTS idx_entities_orgform    ON norric_entities(orgform);
CREATE INDEX IF NOT EXISTS idx_entities_kommunkod  ON norric_entities(kommunkod);
CREATE INDEX IF NOT EXISTS idx_entities_is_active  ON norric_entities(is_active);
CREATE INDEX IF NOT EXISTS idx_entities_name       ON norric_entities(name text_pattern_ops);

CREATE TABLE IF NOT EXISTS norric_entity_snapshots (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr       text NOT NULL,
    snapshot    jsonb NOT NULL,
    diff        jsonb,
    source_run  text NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_orgnr ON norric_entity_snapshots(orgnr);
CREATE INDEX IF NOT EXISTS idx_snapshots_date  ON norric_entity_snapshots(captured_at DESC);
