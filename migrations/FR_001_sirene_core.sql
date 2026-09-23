-- FR-01: Sirene open-data mirror. Licence Ouverte 2.0; non-diffusible natural
-- persons (Art. A123-96 code de commerce) are excluded at ingest.
CREATE TABLE IF NOT EXISTS norric_fr_entities (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), siren text NOT NULL UNIQUE, name text,
 legal_form_code text, legal_form_label text, is_active boolean NOT NULL DEFAULT true,
 registered_at date, dissolved_at date, company_situations jsonb NOT NULL DEFAULT '[]',
 industry_code text, industry_label text, street text, city text, postcode text,
 country_code text NOT NULL DEFAULT 'FR', website text, latest_source_update timestamptz,
 source text NOT NULL DEFAULT 'sirene', raw jsonb,
 first_seen_at timestamptz NOT NULL DEFAULT now(), last_seen_at timestamptz NOT NULL DEFAULT now(),
 last_updated_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_fr_entities_name ON norric_fr_entities(name text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_fr_entities_active ON norric_fr_entities(is_active);
CREATE TABLE IF NOT EXISTS norric_fr_field_changes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), entity_id text NOT NULL, snapshot_date date NOT NULL,
 field_name text NOT NULL, old_value text, new_value text, source text NOT NULL DEFAULT 'sirene',
 source_run text, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_fr_changes_entity ON norric_fr_field_changes(entity_id);
CREATE INDEX IF NOT EXISTS idx_fr_changes_date ON norric_fr_field_changes(snapshot_date DESC);
CREATE TABLE IF NOT EXISTS norric_fr_ingest_state(id smallint PRIMARY KEY DEFAULT 1 CHECK(id=1),last_bulk_at timestamptz,updated_at timestamptz NOT NULL DEFAULT now());
INSERT INTO norric_fr_ingest_state(id) VALUES(1) ON CONFLICT(id) DO NOTHING;
