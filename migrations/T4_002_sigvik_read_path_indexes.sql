-- T4-02: Read-path indexes behind the Sigvik BRF list query (disk-IO budget fix)
--
-- CONTEXT
-- pg_stat_statements on the production Supabase project (checked 2026-09-16)
-- shows the wide GET /api/brfs list query (sigvik-backend: per-row LEFT JOIN
-- LATERAL for the latest arsredovisning and latest energideklaration) at
-- 65.7% of tracked DB time: ~404k calls, ~80.6M rows processed, mean 118 ms.
-- Each lateral subquery resolves "latest per BRF" without a supporting
-- composite index, so every call re-sorts per-row candidate sets.
--
-- ADDS (idempotent)
-- 1. arsredovisningar(orgnr, fiscal_year DESC)
--    serves: WHERE orgnr = b.orgnr ORDER BY fiscal_year DESC LIMIT 1
-- 2. energideklarationer(brf_id, fetched_at DESC)
--    serves: WHERE brf_id = b.id ORDER BY fetched_at DESC LIMIT 1
--
-- APPLY NOTES
-- * Run this file OUTSIDE a transaction: CREATE INDEX CONCURRENTLY is not
--   allowed inside a transaction block.
-- * CONCURRENTLY avoids table locks on the live t4g.nano; IF NOT EXISTS makes
--   re-runs no-ops.
-- * The arsredovisningar / energideklarationer tables belong to the Sigvik
--   schema on the shared Norric Supabase project. The migration lives here
--   because this repo's migrations/ directory is the applied path for that
--   project; sigvik-backend (alembic) has no applied runner yet.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_arsredovisningar_orgnr_fy_desc
    ON arsredovisningar (orgnr, fiscal_year DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_energideklarationer_brf_fetched_desc
    ON energideklarationer (brf_id, fetched_at DESC);
