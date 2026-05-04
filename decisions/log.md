# Decisions Log

## 2026-05-03

### Fix: auth middleware exemption for public signup/checkout routes

**What changed:**
- `server.py`: Added `_OPEN_PATHS = {"/health", "/signup/free", "/checkout", "/webhooks/stripe"}` to `_NorricAuthMiddleware` so these routes bypass Bearer token validation.
- `server.py` `_router`: Added routing branch to forward `_ISSUANCE_PATHS` to `_issuance_app` (imported from `issuance.main`).
- `requirements.txt`: Added `stripe>=8.0.0`, `fastapi>=0.111.0`, `python-dotenv>=1.0.0` — these were only in `issuance/requirements.txt` and caused `ModuleNotFoundError` on startup.

**Verification:** `POST /signup/free` returns 500 (not 401) — auth exemption confirmed working. The 500 is a DB connectivity issue (see below), not an auth regression.

**Resolved (2026-05-04):** Original pooler URL `aws-1-us-east1.pooler.supabase.com` had a typo (missing dash before zone number); Railway DNS couldn't resolve it. Direct DB host (`db.xmifxnhpufsckihregym.supabase.co`) resolves only to IPv6 which Railway can't reach (no Supabase IPv4 add-on). Fixed by updating `DATABASE_URL` in Railway to the correctly-formatted session pooler: `postgresql+psycopg2://postgres.xmifxnhpufsckihregym:***@aws-1-us-east-1.pooler.supabase.com:5432/postgres`. Also added `psycopg2-binary` and forced psycopg2 dialect in `ingestion/db.py` (synchronous SQLAlchemy is incompatible with asyncpg). Verified: `/signup/free` returns 201 with issued key.

**Resolved (2026-05-04):** Both open issues closed — see entries below.

**Reversibility:** High — revert by removing `_OPEN_PATHS` entries and the `_issuance_app` import.

**Review trigger:** None — this is a bug fix, not a strategic choice.

---

## 2026-05-04

### Vendor consolidation: email transport confirmed Resend-only

**Finding:** `issuance/email.py` already used Resend exclusively — `SENDGRID_API_KEY` appeared only in a stale docstring comment in `issuance/main.py`. No SendGrid SDK or HTTP calls existed anywhere in the codebase.

**What changed:**
- `issuance/main.py` docstring: `SENDGRID_API_KEY` → `RESEND_API_KEY`
- `issuance/email.py` `_FROM`: `edgar@norric.io` → `Kreditvakt <hej@norric.io>`

**Blocking item:** `RESEND_API_KEY` is not set in the Railway `norric-mcp` service environment. Email delivery currently logs to stdout and skips send. Add `RESEND_API_KEY` to Railway vars to enable delivery.

**Reversibility:** High — env var change only.

**Review trigger:** None.

---

### DB-backed API key validation with Redis cache

**What changed:**
- `core/db_auth.py` (new): `lookup_key(raw_key)` validates against Redis cache then DB. Redis is optional — graceful fallback to DB-only if `REDIS_URL` unset or Redis down. `last_used_at` updated fire-and-forget in background thread.
- `server.py` `_NorricAuthMiddleware`: validation order is now (1) `NORRIC_API_KEYS` env var (admin/test keys, no I/O), (2) `core.db_auth.lookup_key` via Redis + DB. Attaches `norric_tier` and `norric_auth_source` to ASGI scope.
- `migrations/T2_011_api_keys_last_used.sql`: adds `last_used_at timestamptz` column and `idx_api_keys_key_hash` index. Applied to production DB.

**Verification:** Issued key (`nrk_P16o...`) via `/signup/free`, used it on `/mcp` — HTTP 200, `last_used_at` updated in DB (confirmed via direct query). Auth source: `db` (Redis not configured).

**Reversibility:** Medium — revert `server.py` middleware commit. DB migration is additive (column nullable, backward-compatible).

**Review trigger:** If Redis latency exceeds 5ms p95 or cache hit rate drops below 85% once `REDIS_URL` is added.

---

### Fix: Pricing.tsx CTA hrefs corrected to match backend tier names

**What changed:**
- Silver: `/billing/checkout?tier=silver` → `/checkout?tier=standard&billing=monthly`
- Guld: `/billing/checkout?tier=guld` → `/checkout?tier=standard&billing=annual`
- Premium: `/billing/checkout?tier=premium` → `/checkout?tier=compliance&billing=annual`

**Verification:** Tier/billing params now match `issuance/main.py` `GET /checkout` expected query params.

**Reversibility:** High — frontend change, Vercel auto-deploys on push.

**Review trigger:** None — aligning frontend to existing backend contract.
