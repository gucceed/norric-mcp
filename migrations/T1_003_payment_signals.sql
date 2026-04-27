-- T1-03: Kronofogden payment order signals + scoring view

CREATE TABLE IF NOT EXISTS norric_payment_signals (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr            text NOT NULL,
    case_ref         text,
    creditor_type    text,
    claim_amount_sek bigint,
    filed_at         date,
    resolved_at      timestamptz,
    is_active        boolean NOT NULL DEFAULT true,
    source_run_id    uuid REFERENCES norric_pipeline_runs(id),
    raw_data         jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payment_orgnr   ON norric_payment_signals(orgnr);
CREATE INDEX IF NOT EXISTS idx_payment_filed   ON norric_payment_signals(filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_payment_active  ON norric_payment_signals(orgnr, is_active);

CREATE OR REPLACE VIEW norric_kronofogden_features AS
SELECT
    orgnr,
    COUNT(*)                                         AS case_count_total,
    COUNT(*) FILTER (WHERE is_active = true)         AS case_count_active,
    MAX(filed_at)                                    AS most_recent_filed,
    now()::date - MAX(filed_at)                      AS days_since_last_case,
    SUM(claim_amount_sek) FILTER (WHERE is_active)   AS total_active_claim_sek,
    COUNT(*) FILTER (WHERE filed_at >= now()::date - 180) AS cases_last_6mo
FROM norric_payment_signals
GROUP BY orgnr;
