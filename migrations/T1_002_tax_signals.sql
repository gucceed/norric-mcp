-- T1-02: Skatteverket tax arrears signals

CREATE TABLE IF NOT EXISTS norric_tax_signals (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr           text NOT NULL,
    signal_type     text NOT NULL DEFAULT 'restanslangd',
    amount_sek      bigint,
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    resolved_at     timestamptz,
    is_active       boolean NOT NULL DEFAULT true,
    source_run_id   uuid REFERENCES norric_pipeline_runs(id),
    raw_data        jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tax_signals_active
    ON norric_tax_signals(orgnr, signal_type)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_tax_signals_orgnr ON norric_tax_signals(orgnr);
CREATE INDEX IF NOT EXISTS idx_tax_signals_seen  ON norric_tax_signals(last_seen_at DESC);
