-- T1-07: Municipality diarium cases

CREATE TABLE IF NOT EXISTS norric_diarium_cases (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kommunkod         text NOT NULL,
    municipality      text NOT NULL,
    case_id           text,
    title             text,
    case_type         text,
    handling_unit     text,
    filed_at          date,
    updated_at_source date,
    status            text,
    subject_tags      text[],
    has_pdf           boolean DEFAULT false,
    pdf_text          text,
    source_url        text,
    platform          text,
    raw_data          jsonb,
    scraped_at        timestamptz DEFAULT now(),
    created_at        timestamptz DEFAULT now(),
    UNIQUE(kommunkod, case_id)
);

CREATE INDEX IF NOT EXISTS idx_diarium_kommunkod ON norric_diarium_cases(kommunkod);
CREATE INDEX IF NOT EXISTS idx_diarium_filed     ON norric_diarium_cases(filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_diarium_type      ON norric_diarium_cases(case_type);
CREATE INDEX IF NOT EXISTS idx_diarium_tags      ON norric_diarium_cases USING gin(subject_tags);
