-- T2-01: Kreditvakt company scores — the derived signal layer output

CREATE TABLE IF NOT EXISTS company_scores (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr                text NOT NULL,
    distress_probability float NOT NULL,          -- [0.0, 1.0]
    risk_band            int NOT NULL,             -- 1–5
    insolvency_score     int NOT NULL,             -- legacy 0–100 for UI compat
    signals              jsonb NOT NULL DEFAULT '[]',
    signals_fired        int NOT NULL DEFAULT 0,
    signals_total        int NOT NULL DEFAULT 6,   -- 4 live sources + 2 derived
    scored_at            timestamptz NOT NULL DEFAULT now(),
    data_freshness_hours float,                    -- hours since oldest signal
    score_source         text NOT NULL DEFAULT 'live',  -- 'live' | 'mock'
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_scores_orgnr
    ON company_scores(orgnr);

CREATE INDEX IF NOT EXISTS idx_company_scores_band
    ON company_scores(risk_band DESC);

CREATE INDEX IF NOT EXISTS idx_company_scores_scored_at
    ON company_scores(scored_at DESC);

-- Alert tracking: captures band transitions
CREATE TABLE IF NOT EXISTS company_score_history (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orgnr                text NOT NULL,
    distress_probability float NOT NULL,
    risk_band            int NOT NULL,
    scored_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_score_history_orgnr
    ON company_score_history(orgnr, scored_at DESC);
