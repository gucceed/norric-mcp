# Decisions Log

## 2026-05-03

### Fix: auth middleware exemption for public signup/checkout routes

**What changed:**
- `server.py`: Added `_OPEN_PATHS = {"/health", "/signup/free", "/checkout", "/webhooks/stripe"}` to `_NorricAuthMiddleware` so these routes bypass Bearer token validation.
- `server.py` `_router`: Added routing branch to forward `_ISSUANCE_PATHS` to `_issuance_app` (imported from `issuance.main`).
- `requirements.txt`: Added `stripe>=8.0.0`, `fastapi>=0.111.0`, `python-dotenv>=1.0.0` — these were only in `issuance/requirements.txt` and caused `ModuleNotFoundError` on startup.

**Verification:** `POST /signup/free` returns 500 (not 401) — auth exemption confirmed working. The 500 is a DB connectivity issue (see below), not an auth regression.

**Open infrastructure issue:** `ingestion/db.py` DB connection fails with `could not translate host name "aws-1-us-east1.pooler.supabase.com"` — Supabase pooler hostname not resolvable from Railway's network. Resolution: set `DATABASE_URL` in Railway to use the direct Supabase connection string (session mode, port 5432) instead of the pooler URL. Also added `psycopg2-binary` and forced psycopg2 dialect in `ingestion/db.py` since the synchronous Session is incompatible with asyncpg.

**Reversibility:** High — revert by removing `_OPEN_PATHS` entries and the `_issuance_app` import.

**Review trigger:** None — this is a bug fix, not a strategic choice.

---

### Fix: Pricing.tsx CTA hrefs corrected to match backend tier names

**What changed:**
- Silver: `/billing/checkout?tier=silver` → `/checkout?tier=standard&billing=monthly`
- Guld: `/billing/checkout?tier=guld` → `/checkout?tier=standard&billing=annual`
- Premium: `/billing/checkout?tier=premium` → `/checkout?tier=compliance&billing=annual`

**Verification:** Tier/billing params now match `issuance/main.py` `GET /checkout` expected query params.

**Reversibility:** High — frontend change, Vercel auto-deploys on push.

**Review trigger:** None — aligning frontend to existing backend contract.
