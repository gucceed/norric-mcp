-- 2026_05_13_konkurs_signals.down.sql
-- Rollback of 2026_05_13_konkurs_signals.sql
--
-- STATUS: NOT FOR ROUTINE USE. Only run if rolling back the konkurs ingestor
-- completely. Dropping status_code will lose data for any konkurs rows that
-- have been ingested between the up migration and this down — back them up
-- first via pg_dump if there are any.

BEGIN;

DROP INDEX IF EXISTS idx_norric_payment_signals_orgnr_case_ref;

ALTER TABLE norric_payment_signals
    DROP COLUMN IF EXISTS status_code;

COMMIT;
