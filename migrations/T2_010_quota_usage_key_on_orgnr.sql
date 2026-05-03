-- T2_010: Re-key quota_usage on org_nr (organisation-level quota)
-- All users under the same org_nr share one monthly quota pool.
-- Applied 2026-05-03. Table was empty at migration time.

ALTER TABLE quota_usage RENAME COLUMN key_hash TO org_nr;

-- Verification: SELECT column_name FROM information_schema.columns WHERE table_name='quota_usage' ORDER BY ordinal_position;
-- Expected: org_nr, call_count, period_start, reset_at
