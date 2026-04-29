-- T2-03: Company profiles — cross-signal correlation store (Tier 3 foundation)

CREATE TABLE IF NOT EXISTS company_profiles (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr               text NOT NULL UNIQUE,
    -- Signal correlation — populated when entity appears in 2+ pipelines within 90 days
    correlated_signals  jsonb,
    -- Vigil lifecycle
    lifecycle_stage     text,               -- new_business | growing | transitioning | distressed
    f_skatt_active_at   date,
    f_skatt_revoked_at  date,
    -- Ownership change velocity (aggregate only — no names stored)
    ownership_changes_12m int DEFAULT 0,
    ownership_last_change_at date,
    -- Cross-product signal timestamps
    kreditvakt_scored_at    timestamptz,
    vigil_detected_at       timestamptz,
    last_correlated_at      timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_profiles_orgnr
    ON company_profiles(orgnr);
CREATE INDEX IF NOT EXISTS idx_profiles_lifecycle
    ON company_profiles(lifecycle_stage);
CREATE INDEX IF NOT EXISTS idx_profiles_correlated
    ON company_profiles(last_correlated_at DESC)
    WHERE correlated_signals IS NOT NULL;
