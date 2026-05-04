# Decisions Log

## 2026-05-03

### Fix: auth middleware exemption for public signup/checkout routes

**What changed:**
- `server.py`: Added `_OPEN_PATHS = {"/health", "/signup/free", "/checkout", "/webhooks/stripe"}` to `_NorricAuthMiddleware` so these routes bypass Bearer token validation.
- `server.py` `_router`: Added routing branch to forward `_ISSUANCE_PATHS` to `_issuance_app` (imported from `issuance.main`).
- `requirements.txt`: Added `stripe>=8.0.0`, `fastapi>=0.111.0`, `python-dotenv>=1.0.0` — these were only in `issuance/requirements.txt` and caused `ModuleNotFoundError` on startup.

**Verification:** `POST /signup/free` returns 500 (not 401) — auth exemption confirmed working. The 500 is a DB connectivity issue (see below), not an auth regression.

**Resolved (2026-05-04):** Original pooler URL `aws-1-us-east1.pooler.supabase.com` had a typo (missing dash before zone number); Railway DNS couldn't resolve it. Direct DB host (`db.xmifxnhpufsckihregym.supabase.co`) resolves only to IPv6 which Railway can't reach (no Supabase IPv4 add-on). Fixed by updating `DATABASE_URL` in Railway to the correctly-formatted session pooler: `postgresql+psycopg2://postgres.xmifxnhpufsckihregym:***@aws-1-us-east-1.pooler.supabase.com:5432/postgres`. Also added `psycopg2-binary` and forced psycopg2 dialect in `ingestion/db.py` (synchronous SQLAlchemy is incompatible with asyncpg). Verified: `/signup/free` returns 201 with issued key.

**Open issues (out of scope for this fix):**
- `SENDGRID_API_KEY` not set in Railway — email delivery falls back to stdout log, keys not emailed to users
- `_NorricAuthMiddleware` validates against `NORRIC_API_KEYS` env var only; DB-issued keys return 401 on MCP calls — middleware must query DB to validate issued keys

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
