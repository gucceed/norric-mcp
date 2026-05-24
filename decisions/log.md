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

---

## 2026-05-16: Konkursansökan ingestion live

Built end-to-end bulk-file konkurs ingester for Bolagsverket. First production ingest 2026-05-14 wrote 29,206 real konkurs rows (28,983 AB + 223 BRF, filed_at range 2024-05-14 → 2026-05-08). `/score` now returns `score_source: "live"` with `bolagsverket_petition: true` for any AB/BRF in coverage. Idempotency re-run 2026-05-16 confirmed `inserted=0, updated=29,131` (75 rows aged out of the rolling 24-month window).

**Sources:**
- Bulk file: `https://vardefulla-datamangder.bolagsverket.se/bolagsverket/bolagsverket_bulkfil.zip` (HTTP 200 via curl, no auth, AWS S3-backed, weekly Sunday→Monday cadence).
- Code mapping: kodlista embedded in `bolagsverket.se/apierochoppnadata/nedladdningsbarafiler.2517.html`, fetched via Playwright into `ingestion/bolagsverket/reference/nedladdningsbara_filer.html` and extracted to `kodlista_extracted.json`. Five sections, 64 codes total.

**Critical finding:** The bulk file uses **alphabetic mnemonic codes** (KK-AVOMFO, KKAV-AVORG, KKAVOV-AVSLAVOMFO …), NOT the numeric two-digit codes in Bolagsverket's Näringslivsregistret statuskoder.pdf (20, 21, 22, 24 …). These are two separate code systems. The bulk file is ground truth for ingestion; the numeric system is preserved in `raw_data.status_numeric` per `ALPHABETIC_TO_NUMERIC_MAPPING` in `konkurs_parser.py` for cross-referencing public documentation.

**Eight suffix-variant codes** (KKAVOV-AVSLAVOMFO, KKUHAVD-AVSLAVOMFO, LIUHOR-AVSLAVOMFO, LIUHAVD-AVSLAVOMFO, ACUHOR-AVSLAVOMFO, ACUHAVD-AVSLAVOMFO, FRUHOR-AVSLAVOMFO, FRUHAVD-AVSLAVOMFO) observed in field 7 but undocumented in the kodlista. Tagged `raw_data->>'documentation_status' = 'empirical'` for queryable audit. Apier@ email drafted at `ingestion/bolagsverket/reference/apier-email-draft.md` for confirmation.

**Schema changes:** Additive migration `migrations/2026_05_13_konkurs_signals.sql` — `status_code TEXT` column + UNIQUE INDEX on `(orgnr, case_ref)`. Down migration available. Applied via psycopg2 with pre/post verification.

**Cron:** `bolagsverket.konkurs_ingest` registered in `ingestion/tasks/bolagsverket_tasks.py`, scheduled daily 03:15 Europe/Stockholm in `celeryconfig.py`. Idempotent (UPSERT on UNIQUE), cached zip reused for 7 days, autoretry 3× on exception.

**Reversibility:** HIGH. Additive migration with working down. Cron task disablable by removing the beat entry. `_mock_fallback` in scorer remains gated behind real-orgnr check; reverting konkurs ingestion to mock requires no code change.

**Review trigger:**
- Monthly coverage audit (count of distinct orgnrs with KK-AVOMFO in trailing 365d).
- Any ingestion failure for >3 consecutive days (Resend alert wired via existing pipeline_run telemetry).
- apier@bolagsverket.se reply landing — flip `documentation_status` on 8 suffix-variant rows from `'empirical'` to `'documented'` via SQL in the email-draft file.

**Known issue surfaced (not introduced):** Scorer's Kronofogden count query in `scoring/kreditvakt.py` lacks a `raw_data->>'signal_type'` filter — our konkurs rows are being double-counted as Kronofogden cases. Pre-existing bug, only visible now that real konkurs data is present. Separate fix.

---

## 2026-05-24

### Dashboard REST transport bridge pushed — browser SSE hang workaround

**What changed (commit `373eaae`, pushed to `origin/main` alongside 5 prior unpushed commits including the intelligence MCP tools and score-screen MVP):**

- `kreditvakt/api.py`: three REST endpoints (`/api/v1/score/{orgnr}`, `/api/v1/search`, `/api/v1/contagion-map/{orgnr}`) mirroring `norric_score_v1` / `norric_search_v1` / `norric_contagion_map_v1`. Same Norric envelope; no session handshake; `application/json` with `Content-Length`. MCP remains canonical for non-browser clients.
- `server.py`: `_mcp_asgi = mcp.http_app(json_response=True)` keeps `/mcp` usable from browsers that prefer JSON via `Accept` negotiation. CORS expanded for 127.0.0.1 origins, DELETE, `X-Norric-Key`, `Mcp-Session-Id`, `Mcp-Protocol-Version`, `Accept`; `Mcp-Session-Id` added to `expose_headers`.
- `dashboard/`: REST client replaces the JSON-RPC + handshake plumbing; FNV-1a peer-jitter so same-kommun BRFs don't stack at one pixel; SearchBar gates queries on focus + non-prefill so the navigated /score query isn't races; Vite proxy `agent: false` on `/mcp` disables connection pooling so FastMCP's SSE hold-open can't serialise calls.

**Why:** Browser fetch reads of FastMCP's `text/event-stream` tool-call response bodies hang 20+s after headers arrive (Chrome / Safari / Firefox). Curl and the MCP TypeScript SDK both unaffected. Workarounds attempted (json_response=True alone, Accept negotiation, fresh sockets per request) reduced but did not eliminate. Root cause never conclusively isolated; suspected FastMCP SSE stream lifecycle × browser fetch body buffering. REST bridge sidesteps it entirely for the dashboard's read-only flows.

**Reversibility:** HIGH — REST endpoints are additive; removing them does not affect MCP behaviour.

**Review trigger:** If FastMCP releases a fix for the SSE-body-buffering interop, revisit whether the REST bridge is still worth maintaining.

---

### Blocker flagged — norric_auth refactor NOT pushed; would brick production auth

**What was held back:** Uncommitted local changes to `core/db_auth.py` (rewrites `lookup_key()` to delegate to a `norric_auth.Validator` from a new shared package) and the new `tests/test_auth_smoke.py` (mocks `norric_auth.ApiKey` / `Tier` / `Validator`).

**Why not pushed:** The `norric_auth` package is not in `requirements.txt`, not on GitHub (no `gucceed/norric-auth` repo), and not even a git repo locally (only at `/Users/admin/Code/norric-auth/` as a loose pyproject). The diff has a sys.path fallback to `/Users/admin/Code/norric-auth/src` inside `except ImportError:` — that path does not exist on Railway. Production deploy would: fail the first import → fall through to sys.path.insert → fail the second import → every `lookup_key()` call returns `None` → middleware returns 401 on every request including `/health` if it touches the same path.

**State:** Files left as uncommitted modifications + untracked test, exactly as found. The 2026-05-04 DB-backed validation path is what production is running.

**Reversibility:** HIGH — nothing was changed in the production-bound code.

**Review trigger:** Edgar to either (a) create `gucceed/norric-auth` repo and add a `git+ssh://...` line to `requirements.txt`, (b) move the validator into the existing `gucceed/norric-shared` package, or (c) abandon the refactor and revert `core/db_auth.py`.

---

### Lagprövning — KuL question gates paid Kreditvakt MCP tiers in public distribution; restrict to Free until counsel confirms

**Trigger:** Pre-distribution sweep (2026-05-24 megaprompt). Holding `~/Code/norric/CLAUDE.md` mandates sektorsspecifik lagprövning at scoping; memory entry "KuL tillstånd flagged for Kreditvakt" was 15 days old without a resolving log entry; no prior entry covered MCP-mediated paid-tier delivery specifically.

**Question:** Does selling the Norric MCP Kreditvakt tier suite — `kreditvakt_score_company_v1`, `kreditvakt_batch_score_v1`, `kreditvakt_debt_signals_v1`, `kreditvakt_bankruptcy_status_v1`, `norric_company_profile_v1`, and the Compliance-only `norric_explain_score_v1` — via paid API tiers constitute *kreditupplysningsverksamhet* under kreditupplysningslagen (1973:1173)? If yes, is tillstånd from IMY required before public listing on mcp.so / Anthropic Connectors Directory / PulseMCP / norric.io public pricing?

**Preliminary read (NOT a substitute for counsel):**

1. KuL §3 defines kreditupplysning as "uppgift, omdöme eller råd som lämnas till ledning för bedömning av annans kreditvärdighet eller vederhäftighet i övrigt i ekonomiskt hänseende". Norric outputs are explicit kreditbedömningar (`risk_score` 0–20, `risk_tier` HEALTHY|WATCH|ELEVATED|HIGH|CRITICAL, `distress_probability` internally, plus the explain_score provenance chain) keyed to orgnr. Plain-text reading: Kreditvakt outputs fall inside KuL's scope.

2. KuL applies to juridiska personer as well as konsumenter — företagskreditupplysningar are inside the lagstiftning's scope. Selling them to a third party for fee is the canonical regulated activity.

3. MCP-mediated delivery does not change the analysis. KuL is technology-agnostic; the regulated activity is providing kreditbedömningar to third parties for a fee, regardless of transport (REST, MCP, email PDF, printed letter).

4. `norric_explain_score_v1` (Compliance tier) is the most exposed surface — its provenance + signal breakdown is exactly the auditability output a regulated credit-grantor would use for KuL §9 (saklighetskrav). Selling that capability positions Norric squarely as a kreditupplysningsföretag.

5. Free tier (`norric_status_v1`, `norric_data_freshness_v1`) does NOT return kreditbedömningar — `_status_v1` is service health, `_data_freshness_v1` is pipeline freshness. Free-tier-only distribution does not trigger KuL.

6. **What this prövning cannot answer:** the precise §3 boundary for B2B portfolio-monitoring use vs credit-decision use; whether a tillståndsfri delivery model exists (e.g., raw signal data without a computed score); §13 kreditupplysningskopia obligations for juridiska personer; and the interaction with GDPR Article 28 for buyers redistributing Norric outputs. These are counsel's call.

**Adjacent regelverk surfaced (not resolved here):**

- **MFL §10 (otillbörlig marknadsföring):** `/health` (2026-05-24T) reports 16 tracked companies in Kreditvakt. Listing copy that positions Norric as "Sweden-wide insolvency intelligence" without disclosing the `norric_entities`-membership gate is an MFL risk independent of KuL. To fix in the same doc cleanup as this entry — see follow-up subsections.
- **Konkursansökan dataset:** 29,206 Bolagsverket rows ingested 2026-05-14 are real and queryable, but limited to companies *with* a konkurs filing. Copy must not imply broader coverage than the underlying signal supports.
- **LEK / Avtalsvillkorslagen (1994:1512) för näringsidkare:** Standard/Compliance Stripe checkout would need Swedish-language ToS for SE buyers. Deferred — paid tiers held back from public funnel per decision below.

**Decision:**

1. **Suspend Standard and Compliance tiers from public listings** (mcp.so, Anthropic Connectors Directory, PulseMCP, registry.modelcontextprotocol.io, public norric.io pricing) until counsel confirms tillståndsstatus. Existing issued paid keys keep working — middleware enforcement is unchanged. New paid-tier acquisitions move to a manual qualification + ToS flow off public listing surfaces (`hej@norric.io` lead capture).

2. Free-tier-only positioning for the current distribution sweep: PulseMCP form, Anthropic Connectors Directory submission, mcp.so listing update (the existing 2026-05-08 comment and the registry.modelcontextprotocol.io v1.0.0 entry both name paid tiers — revise via comment update / re-publish).

3. Edgar to engage counsel on: tillståndsansökan, §11/§12/§13 obligations, GDPR Article 28 implications for buyers redistributing Norric outputs, and whether a tillståndsfri offering exists (e.g., raw signal data only, with the scoring layer disclaimed as the customer's own algorithm).

4. `norric_entities` backfill from Bolagsverket bulk is the operational prerequisite for *any* "Sweden-wide" marketing claim after tillstånd lands. Separate sequencing — not in scope of this prövning.

**Reversibility:** HIGH at the listing layer (copy + form edits only; no technical changes). MEDIUM at customer-issuance (existing paid keys keep working; only new public-funnel acquisitions throttled to manual). LOW for the prior-public-footprint blast (registry.modelcontextprotocol.io v1.0.0, mcp.so issue comment, awesome-mcp-servers PR #6042 already exist; cached/indexed copies persist).

**Review trigger:**
- IMY tillstånd granted, OR counsel issues memo on a narrower tillämpningsområde.
- A buyer pre-commits to Compliance tier with KuL liability documented in contract — bespoke private listing may become appropriate.
- IMY publishes new vägledning that materially changes the §3 boundary analysis.
- `norric_entities` backfill crosses 100k entities — re-evaluate "Sweden-wide" copy under MFL.
- This prövning is reviewed annually irrespective of triggers above.

---

### Doc drift cleanup — score scale, tier mapping, stale URLs, listing pricing

**What changed:** Surgical edits across `README.md`, `AGENTS.md`, `registry/servers.yaml`, `registry/mcpso_listing.md`, `registry/anthropic_connector_submission.md` to bring documented surfaces into alignment with: (a) the canonical `risk_score` 0–20 contract locked in the kill-mock-fallback PR per CHANGELOG `Unreleased`, (b) the canonical `mcp.norric.io` endpoint (replacing stale Railway preview hostname per 2026-05-08 entry above), (c) the Free-tier-only public listing positioning from the KuL lagprövning above. Also deleted the superseded `ingestion/bolagsverket/reference/apier_email_draft.md` (underscore) — canonical version is `apier-email-draft.md` (dash).

**Per-file changes:**
- `README.md`: pricing table now shows "Contact" for Standard/Compliance; Free tier rows drop `norric_explain_score_v1` (Compliance-only); Kreditvakt tool descriptions reference `risk_score` 0–20 instead of "0-100 insolvency score".
- `AGENTS.md`: connection URL `mcp.norric.io/mcp`; Pattern 1 example uses `risk_tier in ('HIGH','CRITICAL')` instead of `insolvency_score > 60`; Pattern 3 stale tool names (`sigvik_search_brfs_v1`, `sigvik_brf_score_v1`) replaced with canonical (`sigvik_score_brf_v1` + companions); rate-limit copy aligned with current per-key DB-backed enforcement.
- `registry/servers.yaml`: `tool_count: 19` → `21`; `norric_data_freshness_v1` moved from `paid_tier_tools` to `free_tier_tools`. `norric_explain_score_v1` stays in `paid_tier_tools` (Compliance-gated).
- `registry/mcpso_listing.md`: prices replaced with "Contact"; Free tier description aligned; `nrc_` key prefix corrected to `nrk_`; Kreditvakt example description updated for 0–20 scale.
- `registry/anthropic_connector_submission.md`: Kreditvakt example description updated for 0–20 scale; Free tier line drops `norric_explain_score_v1`; submission URL corrected to Anthropic Connectors Directory Google form per current submission flow (replaces stale `anthropic-quickstarts` reference).

**Reversibility:** HIGH — `git revert` on the doc-cleanup commit; no behavioural change.

**Review trigger:** None — these are alignment edits to existing canonical decisions logged above. If the CHANGELOG `Unreleased` section materially changes (e.g. additional public field removals), this entry's tool descriptions need re-checking.

**Out of scope (not done):**
- `INTEGRATION.md` — grepped for `0-100` / `verdict` / `insolvency_score` / `distress_probability`; returned nothing. File describes the provenance-layer wire-up (Steps 1–9), not the public API surface. No edits required in this pass.
- `registry/submit.py` and generators — left unchanged; the YAML-to-payload generators correctly emit whatever YAML contains, so re-running `python -m registry.submit norric-mcp` after YAML edits will produce free-tier-aware payloads automatically. Re-submission to PulseMCP and updated mcp.so comment are manual steps tracked in the session summary.

