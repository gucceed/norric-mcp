-- NO-01: Brønnøysund Enhetsregisteret core tables - Norway country three.
-- Official open data, NLOD 2.0. No role/person or beneficial-owner data.
CREATE TABLE IF NOT EXISTS norric_no_entities (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_number text NOT NULL UNIQUE,
 name text, legal_form_code text, legal_form_label text, is_active boolean NOT NULL DEFAULT true,
 registered_at date, founded_at date, bankruptcy boolean NOT NULL DEFAULT false,
 under_liquidation boolean NOT NULL DEFAULT false, forced_liquidation boolean NOT NULL DEFAULT false,
 industry_code text, industry_label text, street text, city text, postcode text,
 municipality_code text, country_code text, raw_address jsonb, phone text, email text, website text,
 source text NOT NULL DEFAULT 'brreg_bulk', raw jsonb,
 first_seen_at timestamptz NOT NULL DEFAULT now(), last_seen_at timestamptz NOT NULL DEFAULT now(),
 last_updated_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_no_entities_org ON norric_no_entities(org_number);
CREATE INDEX IF NOT EXISTS idx_no_entities_name ON norric_no_entities(name text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_no_entities_active ON norric_no_entities(is_active);
CREATE TABLE IF NOT EXISTS norric_no_field_changes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), entity_id text NOT NULL, entity_type text NOT NULL DEFAULT 'company',
 snapshot_date date NOT NULL, field_name text NOT NULL, old_value text, new_value text,
 source text NOT NULL DEFAULT 'brreg', source_run text, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_no_changes_entity ON norric_no_field_changes(entity_id);
CREATE INDEX IF NOT EXISTS idx_no_changes_date ON norric_no_field_changes(snapshot_date DESC);
CREATE TABLE IF NOT EXISTS norric_no_events (
 update_id bigint PRIMARY KEY, org_number text NOT NULL, changed_at timestamptz, change_type text,
 payload jsonb, imported_at timestamptz NOT NULL DEFAULT now(), processed_at timestamptz);
CREATE INDEX IF NOT EXISTS idx_no_events_org ON norric_no_events(org_number);
CREATE TABLE IF NOT EXISTS norric_no_ingest_state (
 id smallint PRIMARY KEY DEFAULT 1 CHECK(id=1), last_update_id bigint NOT NULL DEFAULT 0,
 last_bulk_at timestamptz, last_reconcile_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now());
INSERT INTO norric_no_ingest_state(id) VALUES(1) ON CONFLICT(id) DO NOTHING;
