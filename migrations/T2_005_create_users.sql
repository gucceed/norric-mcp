-- T2_005: Users table for Free tier registration
-- Auth: email + org_nr (Swedish format XXXXXX-XXXX, Luhn-validated at application layer)
-- No BankID yet — Q3 addition

CREATE TYPE IF NOT EXISTS user_tier AS ENUM (
    'free', 'silver', 'guld', 'premium', 'enterprise'
);

CREATE TABLE IF NOT EXISTS users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             text NOT NULL UNIQUE,
    org_nr            text NOT NULL,
    tier              user_tier NOT NULL DEFAULT 'free',
    stripe_customer_id text,
    stripe_subscription_id text,
    email_verified    boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_active_at    timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_org_nr ON users(org_nr);
CREATE INDEX IF NOT EXISTS idx_users_tier ON users(tier);

-- Enterprise inquiry table (no Stripe SKU — manual contract)
CREATE TABLE IF NOT EXISTS enterprise_inquiries (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email       text NOT NULL,
    org_nr      text,
    company     text,
    message     text,
    notified_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- DPA signatures (required for enskild firma full creditor name access at Guld tier)
CREATE TABLE IF NOT EXISTS dpa_signatures (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signed_at   timestamptz NOT NULL DEFAULT now(),
    document_version text NOT NULL,
    ip_hash     text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dpa_user_id ON dpa_signatures(user_id);
