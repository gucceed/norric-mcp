-- ============================================================
-- SIGNAL_001_core_tables.sql
-- Norric SIGNAL — procurement intelligence tables
-- Safe to run on live DB — no existing tables modified
-- ============================================================

-- ── municipalities ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS municipalities (
    id                      INTEGER PRIMARY KEY,
    name                    VARCHAR(100) NOT NULL,
    region                  VARCHAR(100) NOT NULL,
    county_code             VARCHAR(4)   NOT NULL,
    platform                VARCHAR(50)  NOT NULL,
    scrape_url              TEXT         NOT NULL,
    scrape_config           JSONB,
    active                  BOOLEAN      NOT NULL DEFAULT true,
    last_scraped_at         TIMESTAMPTZ,
    last_scrape_ok          BOOLEAN,
    contracts_per_week_avg  SMALLINT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_municipalities_region   ON municipalities(region);
CREATE INDEX IF NOT EXISTS ix_municipalities_platform ON municipalities(platform);
CREATE INDEX IF NOT EXISTS ix_municipalities_active   ON municipalities(active);

-- ── signal_contracts ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signal_contracts (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_platform         VARCHAR(50) NOT NULL,
    source_url              TEXT        NOT NULL UNIQUE,
    municipality_id         INTEGER     REFERENCES municipalities(id),
    municipality            VARCHAR(100) NOT NULL,
    title                   TEXT        NOT NULL,
    description             TEXT,
    contracting_authority   TEXT,
    supplier_name           TEXT,
    supplier_orgnr          VARCHAR(20),
    contract_value_sek      BIGINT,
    award_date              DATE,
    contract_start          DATE,
    contract_end            DATE,
    category_raw            TEXT,
    sector                  VARCHAR(50),
    subcategory             VARCHAR(100),
    kv_score                SMALLINT,
    kv_tier                 VARCHAR(20),
    kv_flags                JSONB,
    kv_checked_at           TIMESTAMPTZ,
    classified_at           TIMESTAMPTZ,
    scored_at               TIMESTAMPTZ,
    alerted_at              TIMESTAMPTZ,
    scraped_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_html                TEXT
);

CREATE INDEX IF NOT EXISTS ix_sc_municipality_id ON signal_contracts(municipality_id);
CREATE INDEX IF NOT EXISTS ix_sc_supplier_orgnr  ON signal_contracts(supplier_orgnr);
CREATE INDEX IF NOT EXISTS ix_sc_award_date      ON signal_contracts(award_date DESC);
CREATE INDEX IF NOT EXISTS ix_sc_sector          ON signal_contracts(sector);
CREATE INDEX IF NOT EXISTS ix_sc_scraped_at      ON signal_contracts(scraped_at DESC);

CREATE INDEX IF NOT EXISTS ix_sc_kv_tier_active
    ON signal_contracts(kv_score DESC)
    WHERE kv_tier IN ('HIGH', 'CRITICAL');

CREATE INDEX IF NOT EXISTS ix_sc_unclassified
    ON signal_contracts(scraped_at)
    WHERE sector IS NULL;

CREATE INDEX IF NOT EXISTS ix_sc_unscored
    ON signal_contracts(scraped_at)
    WHERE supplier_orgnr IS NOT NULL AND kv_score IS NULL;

ALTER TABLE signal_contracts
    ADD COLUMN IF NOT EXISTS search_vector TSVECTOR
    GENERATED ALWAYS AS (
        to_tsvector('swedish',
            coalesce(title, '')                 || ' ' ||
            coalesce(description, '')           || ' ' ||
            coalesce(supplier_name, '')         || ' ' ||
            coalesce(contracting_authority, '') || ' ' ||
            coalesce(municipality, '')
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS ix_sc_search ON signal_contracts USING GIN(search_vector);

-- ── signal_subscriptions ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS signal_subscriptions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id         UUID        NOT NULL,
    name                VARCHAR(200),
    sectors             TEXT[],
    municipality_ids    INTEGER[],
    min_value_sek       BIGINT,
    supplier_orgnrs     TEXT[],
    keywords            TEXT[],
    kv_tier_threshold   VARCHAR(20),
    webhook_url         TEXT,
    webhook_secret      VARCHAR(64),
    email_digest        BOOLEAN NOT NULL DEFAULT true,
    sms_critical        BOOLEAN NOT NULL DEFAULT false,
    active              BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ss_customer_id ON signal_subscriptions(customer_id);
CREATE INDEX IF NOT EXISTS ix_ss_active      ON signal_subscriptions(active);

-- ── signal_delivery_log ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS signal_delivery_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID        NOT NULL,
    contract_id     UUID        NOT NULL REFERENCES signal_contracts(id),
    delivery_type   VARCHAR(20) NOT NULL,
    http_status     SMALLINT,
    error_message   TEXT,
    payload_hash    VARCHAR(64),
    delivered_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sdl_subscription_id ON signal_delivery_log(subscription_id);
CREATE INDEX IF NOT EXISTS ix_sdl_contract_id     ON signal_delivery_log(contract_id);
CREATE INDEX IF NOT EXISTS ix_sdl_delivered_at    ON signal_delivery_log(delivered_at DESC);

CREATE INDEX IF NOT EXISTS ix_sdl_failures
    ON signal_delivery_log(delivered_at)
    WHERE http_status NOT IN (200, 201, 202);

-- ── Supplier risk view ────────────────────────────────────────
CREATE OR REPLACE VIEW signal_supplier_risk AS
SELECT
    sc.supplier_orgnr                                     AS orgnr,
    sc.supplier_name                                      AS name,
    COUNT(*)                                              AS contract_count,
    SUM(sc.contract_value_sek)                            AS total_contract_value_sek,
    MAX(sc.award_date)                                    AS latest_award_date,
    MAX(sc.kv_score)                                      AS kv_score_current,
    (ARRAY_AGG(sc.kv_tier ORDER BY sc.kv_score DESC))[1] AS kv_tier_current,
    MAX(sc.kv_checked_at)                                 AS kv_last_checked,
    ARRAY_AGG(DISTINCT sc.municipality)                   AS municipalities,
    ARRAY_AGG(DISTINCT sc.sector)
        FILTER (WHERE sc.sector IS NOT NULL)              AS sectors,
    COUNT(*) FILTER (
        WHERE sc.contract_end > CURRENT_DATE
           OR sc.contract_end IS NULL
    )                                                     AS active_contract_count,
    SUM(sc.contract_value_sek) FILTER (
        WHERE sc.contract_end > CURRENT_DATE
           OR sc.contract_end IS NULL
    )                                                     AS active_contract_value_sek
FROM signal_contracts sc
WHERE sc.supplier_orgnr IS NOT NULL
GROUP BY sc.supplier_orgnr, sc.supplier_name;
