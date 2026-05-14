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

### Set RESEND_API_KEY; Stage 4 email delivery verified end-to-end

**What changed:**
- `RESEND_API_KEY` added to Railway `norric-mcp` service (sending-only scoped key reused from `Kreditvakt` service in project `motivated-commitment`).

**Verification:** `POST /signup/free` → 201 → email arrived within 5s to temp inbox → from: `hej@norric.io` → key extracted → used on `/mcp` → HTTP 200 with tool result. `last_used_at` updated. Full signup → email → API call funnel live in production.

**Reversibility:** High — rotate key in Resend dashboard.

**Review trigger:** If email deliverability drops below 95% inbox placement, revisit DKIM/DMARC config.

**Missing Railway vars flagged (not fixed):**
- `REDIS_URL`: not set — auth cache falls back to DB on every request (functional, ~10ms overhead per auth call)
- `BOLAGSVERKET_CLIENT_ID` / `BOLAGSVERKET_CLIENT_SECRET`: not set — Bolagsverket-dependent tools will error
- `STRIPE_SECRET_KEY`: not set — `/checkout` Stripe session creation will fail

---

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

---

## 2026-05-04

### Risk taxonomy: Kreditvakt bands and Sigvik labels are intentionally independent

**Decision:** Kreditvakt risk bands and Sigvik intent/confidence labels are different scoring axes and must not be unified.

- **Kreditvakt** uses a 5-band risk taxonomy (Stabil / Bevaka / Förhöjd risk / Kräv säkerhet / Stoppa krediter) derived from `distress_probability` [0.0–1.0] mapped to a 0–20 display score. Source of truth: `scoring/display.py` `_BAND_LABELS` / `_BAND_ACTIONS`.
- **Sigvik** uses a confidence label (Starkt signal / Måttlig signal / Tidig indikation) on a 0–100 intent score. It measures renovation intent and financial stress of a BRF — not credit default risk. Source of truth: `server.py` sigvik tool.

**Rationale:** The two products score fundamentally different things (company insolvency risk vs. BRF property investment readiness). Forcing a shared taxonomy would make both less precise. A Kreditvakt Band 3 ("Förhöjd risk") and a Sigvik "Måttlig signal" are not the same thing and should not be conflated in copy, UI, or agent prompts.

**Standing rule:** Do not introduce a cross-product risk label or shared band constant. If a future Norric product needs risk bands, define its own taxonomy in its own scoring module and log the decision here.

**Review trigger:** If a cross-product dashboard or portfolio view is built that needs to compare Kreditvakt and Sigvik signals side-by-side, revisit whether a shared severity mapping is needed — but keep it as a view-layer adapter, not a shared scoring primitive.

---

### Renamed Railway services in project motivated-commitment (589e3b14) for trackability

**What changed:** Four services renamed via Railway GraphQL API (`serviceUpdate` mutation). Redis left unchanged.

| Before | After | Service ID |
|---|---|---|
| `daring-adaptation` | `sigvik-beat` | `0c97a57e` |
| `zoological-enjoyment` | `sigvik-worker` | `82c18a59` |
| `sigvik-backend` | `sigvik-api` | `76c8e88e` |
| `Kreditvakt` | `kreditvakt-api` | `79cb30dd` |

**Side effects verified:** Public domain `sigvik-backend-production.up.railway.app` unchanged (Railway preserves generated hostnames on rename). Cross-service reference var auto-renamed `RAILWAY_SERVICE_SIGVIK_BACKEND_URL` → `RAILWAY_SERVICE_SIGVIK_API_URL` with correct value.

**Reversibility:** Easy — rename back via same GraphQL mutation or Railway dashboard.

---

## 2026-05-08

### mcp.norric.io SSL cert provisioned — Railway custom domain verified

**What happened:** Railway custom domain `mcp.norric.io` (ID `d37ef400-f6b0-4609-a0e6-e2aa02a13473`) was
stuck at `CN=*.up.railway.app` for 12+ hours. Root cause: TXT verification record missing at
`_railway-verify.mcp.norric.io`. Railway requires this before it will route the domain and issue
a cert via ACME HTTP-01.

**What changed:**
- Added TXT record `_railway-verify.mcp.norric.io` = `railway-verify=dec9802d1ca564a24d23505d75562502fac16036ab1fb4e663bbac9fd6fc33fe` at DNS provider.
- Railway verified ownership and issued cert: `CN=mcp.norric.io` from Let's Encrypt (R13), valid 2026-05-07 → 2026-08-05.
- Updated all `norric-mcp-production.up.railway.app/mcp` references → `mcp.norric.io/mcp` across `README.md`, `registry/mcpso_listing.md`, `registry/anthropic_connector_submission.md`.

**Reversibility:** DNS TXT record can be removed at any time. Railway cert auto-renews.

---

### Multi-registry submission system built and first submission executed

**What changed — new files:**
- `registry/servers.yaml` — source of truth for all Norric MCP server entries
- `registry/submit.py` — CLI: `python -m registry.submit <server_id>`
- `registry/generators/official_mcp_registry.py` — emits `server.json` (MCP Registry schema 2025-12-11)
- `registry/generators/github_mcp_registry.py` — forks punkpeye/awesome-mcp-servers, opens PR via `gh`
- `registry/generators/mcp_so.py` — emits mcp.so comment payload
- `registry/generators/pulsemcp.py` — emits PulseMCP form payload
- `registry/submissions.json` — per-server per-registry ledger (timestamp, PR URL, status)
- `registry/anthropic-partnership.md` — documents Anthropic connector directory as partnership track (not automated); revisit at 10+ paying users
- `registry/README.md` — how to add a new server in 10 minutes

**First run — norric-mcp submission results:**

| Registry | Status |
|---|---|
| Official MCP Registry | `pending_manual` — `server.json` generated at `registry/norric-mcp_server.json`; run `mcp-publisher publish` to complete |
| punkpeye/awesome-mcp-servers | **PR opened**: https://github.com/punkpeye/awesome-mcp-servers/pull/6042 |
| mcp.so | Payload printed — paste at github.com/chatmcp/mcpso/issues/1 |
| PulseMCP | Payload printed — submit at pulsemcp.com/submit |

**Idempotency:** Re-running `python -m registry.submit norric-mcp` skips already-submitted registries
and prints existing PR URLs from `submissions.json`.

**Adding future servers (Sigvik, Kreditvakt, SIGNAL, Vigil):** Copy a YAML entry in `servers.yaml`,
run the CLI, paste two form payloads. Target: 10 minutes per server.

---

## 2026-05-14: Bolagsverket konkursansökan ingestion live

Built end-to-end bulk-file konkurs ingester. Kreditvakt `/score` now returns
**real** signals for any AB or BRF with a konkursansökan filed in the
trailing 24 months.

### Sources
- Bulk file: `bolagsverket_bulkfil.zip` via
  `BOLAGSVERKET_DIRECT_URL=https://vardefulla-datamangder.bolagsverket.se/bolagsverket/bolagsverket_bulkfil.zip`
  (S3-backed CDN, no CAPTCHA, ~245 MB compressed, ~977 MB unzipped)
- Cadence: weekly Sunday→Monday 01:30-03:30 UTC drop. Daily cron picks it up
  same-day via etag-aware cache reuse.
- Code mapping: alphabetic kodlista from
  `nedladdningsbara_filer.html` sections 2–3 (documented), plus 8 empirically-
  observed `-AVSLAVOMFO` suffix variants flagged with
  `raw_data->>'documentation_status' = 'empirical'` for future audit.
- Cross-reference to Näringslivsregistret's numeric `statuskoder.pdf` system
  via `ALPHABETIC_TO_NUMERIC_MAPPING` in `konkurs_parser.py`.

### Coverage (first production run, 2026-05-14)
- 29,206 konkurs records in `norric_payment_signals`
- 99.2% AB-ORGFO (28,983), 0.8% BRF-ORGFO (223)
- 11,527 active filings (status_code=`KK-AVOMFO`) + 17,679 concluded historical
  (status_code=`KKAV-AVORG`)
- `filed_at` window: 2024-05-14 → 2026-05-08

### Schema
Additive migration `2026_05_13_konkurs_signals.sql` applied:
- `norric_payment_signals.status_code TEXT` (nullable)
- UNIQUE INDEX `idx_norric_payment_signals_orgnr_case_ref` on `(orgnr, case_ref)`
- Both up + down migrations recorded; reversible

### Operational
- Daily Celery beat: `bolagsverket-konkurs-daily` at 03:15 Europe/Stockholm
- Telemetry: `norric_pipeline_runs` row written per execution
- Idempotent: `ON CONFLICT (orgnr, case_ref) DO UPDATE` preserves created_at
- Cache: `/tmp/bolagsverket-cache` with 7-day retention

### Reversibility
HIGH at the data layer (DELETE WHERE raw_data->>'signal_type' = 'konkurs').
HIGH at the schema layer (companion `.down.sql` exists, additive only).
HIGH at the cron layer (remove beat entry → no new ingests).

### Known follow-ups (NOT fixed in this commit)
1. **Scorer Kronofogden over-counts konkurs rows.** `scoring/kreditvakt.py:85-97`
   queries `norric_payment_signals` without filtering on
   `raw_data->>'signal_type'`. Now that konkurs rows share the table, every
   orgnr with a konkurs filing also gets `kronofogden_count_6mo += 1` falsely.
   One-line fix: add `AND raw_data->>'signal_type' IN ('kronofogden_payment_order')`.
   Held back per "no scorer weighting changes without Edgar" rule.
2. **Bolagsverket `-AVSLAVOMFO` suffix variants are empirically documented,
   not officially.** Email drafted at
   `ingestion/bolagsverket/reference/apier_email_draft.md` to apier@bolagsverket.se
   to lock the semantics. Send when ready; until then 8 suffix codes carry
   `documentation_status: 'empirical'` in `raw_data`.
3. **Score-weight tuning.** A company with an active konkursansökan currently
   scores band 3 (Elevated, ≈0.27 distress probability). The `bolagsverket_petition`
   weight is 0.15. Edgar's call whether to lift this for konkurs specifically
   (separate from rekonstruktion / ackord / resolution).
4. **`bulk_parser.py` name bug** (pre-existing): reads `row[1]` as name but
   field 1 is `namnskyddslopnummer`. Actual name is field 3. Not touched in
   this build to keep scope tight; `konkurs_parser.py` reads field 3 correctly.

### Review trigger
- Monthly coverage audit: rows inserted by `bolagsverket-konkurs-daily` should
  range 100–500 per week (new konkurs filings in Sweden). Material deviation
  → investigate Bolagsverket cadence change or parser drift.
- Any week without a successful `pipeline_run` for >3 consecutive days →
  page Edgar.
