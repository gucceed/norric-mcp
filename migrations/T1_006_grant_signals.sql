-- T1-06: Boverket grant signals

CREATE TABLE IF NOT EXISTS norric_grant_signals (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       text NOT NULL,
    entity_type     text NOT NULL,
    grant_type      text NOT NULL,
    energiklass     text,
    eu_deadline_flag boolean,
    applied_at      date,
    approved_at     date,
    amount_sek      bigint,
    status          text,
    source          text NOT NULL,
    raw_data        jsonb,
    created_at      timestamptz DEFAULT now(),
    UNIQUE(entity_id, grant_type, applied_at)
);

CREATE INDEX IF NOT EXISTS idx_grants_entity  ON norric_grant_signals(entity_id);
CREATE INDEX IF NOT EXISTS idx_grants_type    ON norric_grant_signals(grant_type);
CREATE INDEX IF NOT EXISTS idx_grants_eu_flag ON norric_grant_signals(eu_deadline_flag) WHERE eu_deadline_flag = true;
