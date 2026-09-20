-- DK-01: CVR (Det Centrale Virksomhedsregister) core tables - Denmark country two.
--
-- Mirrors the Swedish T1_001 entity + field-change shape for Danish companies.
-- Source: Datafordeler CVR Fildownload (weekly total downloads, CC BY 4.0)
-- plus CVR_Events via the entity-based GraphQL service.
-- No CVRPerson, no beneficial-owner (reelle ejere) data: both are
-- access-restricted and are intentionally absent from this schema.

CREATE TABLE IF NOT EXISTS norric_dk_entities (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cvr_number          text NOT NULL UNIQUE,          -- 8 digits, text to preserve format
    name                text,                          -- current legal name (Danish, never translated)
    legal_form_code     text,                          -- virksomhedsform code, Danish canonical
    legal_form_label    text,                          -- Danish label as issued by Erhvervsstyrelsen
    status_code         text,                          -- virksomhedsstatus code as issued
    status_label        text,
    is_active           boolean NOT NULL DEFAULT true,
    started_at          date,                          -- startdato
    ceased_at           date,                          -- ophorsdato
    industry_code       text,                          -- hovedbranche (DB07) code
    industry_label      text,
    street              text,
    city                text,
    postcode            text,
    municipality_code   text,
    country_code        text,
    raw_address         text,
    phone               text,
    email               text,
    website             text,
    registrering_fra    timestamptz,                   -- CVR bitemporal registration time
    registrering_til    timestamptz,
    virkning_fra        timestamptz,                   -- CVR bitemporal effect time
    virkning_til        timestamptz,
    datafordeler_row_id text,                          -- object_datafordelerRowId (event refetch key)
    source              text NOT NULL DEFAULT 'cvr_fildownload',
    raw                 jsonb,                         -- raw source row for not-yet-mapped fields
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    last_updated_at     timestamptz NOT NULL DEFAULT now(),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dk_entities_cvr        ON norric_dk_entities(cvr_number);
CREATE INDEX IF NOT EXISTS idx_dk_entities_is_active  ON norric_dk_entities(is_active);
CREATE INDEX IF NOT EXISTS idx_dk_entities_name       ON norric_dk_entities(name text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_dk_entities_municipality ON norric_dk_entities(municipality_code);

CREATE TABLE IF NOT EXISTS norric_dk_field_changes (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id     text NOT NULL,               -- cvr_number
    entity_type   text NOT NULL DEFAULT 'company',
    snapshot_date date NOT NULL,
    field_name    text NOT NULL,
    old_value     text,
    new_value     text,
    source        text NOT NULL DEFAULT 'cvr', -- cvr_fildownload | cvr_events
    source_run    text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dk_changes_entity  ON norric_dk_field_changes(entity_id);
CREATE INDEX IF NOT EXISTS idx_dk_changes_date    ON norric_dk_field_changes(snapshot_date DESC);

CREATE TABLE IF NOT EXISTS norric_dk_events (
    event_id         bigint PRIMARY KEY,        -- Datafordeler eventid
    entity_name      text NOT NULL,             -- e.g. CVR_Virksomhed
    event_action     text,                      -- Datafordeler eventaction (Create/Update/Delete)
    sequence_number  bigint,                    -- datafordelerRegisterImportSequenceNumber
    object_id        text,
    object_row_id    text,                      -- object_datafordelerRowId
    object_status    text,
    registrering_fra timestamptz,
    registrering_til timestamptz,
    virkning_fra     timestamptz,
    virkning_til     timestamptz,
    payload          jsonb,                     -- raw event node
    imported_at      timestamptz NOT NULL DEFAULT now(),
    processed_at     timestamptz
);

CREATE INDEX IF NOT EXISTS idx_dk_events_sequence  ON norric_dk_events(sequence_number);
CREATE INDEX IF NOT EXISTS idx_dk_events_processed ON norric_dk_events(processed_at);

-- Single-row checkpoint/state table for the CVR pipelines.
CREATE TABLE IF NOT EXISTS norric_dk_ingest_state (
    id                   smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_sequence_number bigint NOT NULL DEFAULT 0,
    last_event_id        bigint NOT NULL DEFAULT 0,
    last_bulk_filename   text,
    last_bulk_at         timestamptz,
    last_reconcile_at    timestamptz,
    updated_at           timestamptz NOT NULL DEFAULT now()
);

INSERT INTO norric_dk_ingest_state (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;
