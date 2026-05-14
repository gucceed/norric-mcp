-- 2026_05_13_konkurs_signals.sql
-- Additive migration for Bolagsverket konkursansökan ingestion.
--
-- STATUS: NOT YET APPLIED — awaiting Edgar's go.
-- Drafted 2026-05-14 as Phase 3 of the konkurs-ingestor build.
--
-- ADDS
-- 1. status_code TEXT column on norric_payment_signals — holds the
--    Bolagsverket bulk-file event code for this filing (e.g. "KK-AVOMFO"
--    while pending, "KKAVOV-AVSLAVOMFO" once concluded with overskott).
--    Alphabetic codes per kodlista in nedladdningsbara_filer.html
--    (sections 2 + 3). Näringslivsregistret's statuskoder.pdf uses a
--    different numeric system; that system is held in raw_data via
--    ALPHABETIC_TO_NUMERIC_MAPPING (see konkurs_parser.py).
-- 2. UNIQUE INDEX (orgnr, case_ref) — enables ON CONFLICT upsert by stable
--    filing identity. case_ref is set by the konkurs ingester to
--    f"bv-konkurs-{orgnr}-{initiation_date}", stable across the filing
--    lifecycle. Other signal sources may leave case_ref NULL; PostgreSQL
--    treats NULLs as distinct in UNIQUE INDEXes, so non-konkurs rows with
--    NULL case_ref will not collide.
--
-- SAFETY
-- Additive only. norric_payment_signals is currently empty (per the
-- 2026-05-10 mock-fix diagnosis), so the UNIQUE INDEX builds instantly.
-- The prevailing migration style in this directory does not use CONCURRENTLY;
-- matching that. Switch to CONCURRENTLY if the table later holds data and
-- the runner supports out-of-transaction DDL.
--
-- DOWN MIGRATION
-- See companion file 2026_05_13_konkurs_signals.down.sql

BEGIN;

ALTER TABLE norric_payment_signals
    ADD COLUMN IF NOT EXISTS status_code TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_norric_payment_signals_orgnr_case_ref
    ON norric_payment_signals (orgnr, case_ref);

COMMENT ON COLUMN norric_payment_signals.status_code IS
'Bolagsverket bulk-file event code (alphabetic mnemonic per kodlista in '
'ingestion/bolagsverket/reference/nedladdningsbara_filer.html). '
'Initiation codes documented (e.g. KK-AVOMFO = konkurs inledd, '
'FR-AVOMFO = företagsrekonstruktion inledd). '
'Resolution-suffix variants (-AVSLAVOMFO, -AVORG) observed empirically; '
'pattern: base initiation code + suffix indicating procedural outcome. '
'Näringslivsregistret numeric equivalent in raw_data.status_numeric per '
'ALPHABETIC_TO_NUMERIC_MAPPING in konkurs_parser.py.';

COMMIT;
