-- T2_004: Add hysteresis tracking to company_scores
-- last_displayed_band: the band currently shown to users (may lag natural band)
-- last_band_change_at: when the displayed band last actually moved (for "stable since X" display)

ALTER TABLE company_scores
    ADD COLUMN IF NOT EXISTS last_displayed_band SMALLINT,
    ADD COLUMN IF NOT EXISTS last_band_change_at TIMESTAMPTZ;

-- Backfill: set last_displayed_band from current natural band
-- Band boundaries on distress_probability: <0.20 → 1, <0.40 → 2, <0.60 → 3, <0.80 → 4, else → 5
UPDATE company_scores
SET
    last_displayed_band = CASE
        WHEN distress_probability < 0.20 THEN 1
        WHEN distress_probability < 0.40 THEN 2
        WHEN distress_probability < 0.60 THEN 3
        WHEN distress_probability < 0.80 THEN 4
        ELSE 5
    END,
    last_band_change_at = scored_at
WHERE last_displayed_band IS NULL;
