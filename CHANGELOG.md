# Changelog

All notable changes to norric-mcp.

## Unreleased

### Breaking

- **`score_source: "mock"` removed.** Orgnrs without signal data now return
  `score_source: "no_signals"` with `risk_score`/`risk_band`/`risk_tier` set
  to `null`, or HTTP 404 (`orgnr_not_ingested`) if the orgnr is not in
  `norric_entities`. SDK consumers must handle null `risk_score`.
- **Canonical risk-field family locked:** `risk_score` (0–20, ascending=worse),
  `risk_band` (1–5), `risk_tier` (`HEALTHY|WATCH|ELEVATED|HIGH|CRITICAL`).
  Removed from `/api/score/{orgnr}` response: `display_score`, `band`,
  `band_label`, `band_action`, `confidence_label`, `insolvency_score`.
  Internal DB column `insolvency_score` unchanged; only the public field
  is gone. Swedish marketing strings (`band_action`, `confidence_label`)
  removed alongside `band_label` — all three were the same vocabulary-leak
  class; one breaking change now beats three breaking changes later.
- **Envelope metadata added:** `scale: "0-20"` and `polarity: "ascending_risk"`
  in every 200 response. Defensive signal for integrators who pattern-match
  against UC/Creditsafe conventions.
- **Personnummer / samordningsnummer rejected at API boundary** (HTTP 400).
  Norric Kreditvakt only scores juridiska personer; the boundary is enforced
  mechanically in `_validate_orgnr`, before any DB lookup.
- **HTTP 404 for orgnrs not in `norric_entities`** (`orgnr_not_ingested`).
  Bright line: membership in `norric_entities` = coverage commitment;
  signal presence = current state. Different questions, different status codes.
- **Deregistered companies stay 200**, with `entity.status: "deregistered"`
  and `entity.deregistered_at`. Portfolio monitoring loops never silently drop
  entities the customer still tracks.
- **All four sibling Kreditvakt MCP tools rewritten** to call `score_from_db`
  through a shared `_score_orgnr_via_db` helper. Each returns the canonical
  risk family + entity status only. Removed fields (had no real data source):
  `industry`, `org_age_years`, `registered_year`, `verdict`,
  `f_skatt_active`, `arende_*` (pending-case fields), `skuld_published_date`,
  `kronofogden_escalated`, `konkurs_date`. These return when the underlying
  ingestion pipelines land.
  - `kreditvakt_batch_score_v1` — portfolio_risk_summary now uses
    HEALTHY/WATCH/ELEVATED/HIGH/CRITICAL buckets; weighted_avg renamed
    `weighted_avg_risk_score`. Per-entry shape uses risk_score/risk_band/risk_tier.
  - `kreditvakt_debt_signals_v1` — returns only Skatteverket/Kronofogden
    fields backed by `norric_tax_signals` / `norric_payment_signals`.
  - `kreditvakt_bankruptcy_status_v1` — returns `konkurs_filed` from
    `bolagsverket_petition` + `entity_status` (live deregistered flag) only.
  - `norric_company_profile_v1` — canonical risk family + lifecycle/ownership
    null-stubs (Vigil pipeline still pending).

### Added

- `docs/no-fabrication-contract.md` — invariant + guardrails.
- `tests/test_no_fabrication_imports.py` — AST guardrail blocking fabricator
  imports from `scoring/`, `kreditvakt/`, `mcp_tools/`, `tools/`, AND `server.py`.
  Includes `test_fabricator_file_deleted` — fails if `tools/kreditvakt_engine.py`
  reappears.
- `tests/test_no_fabrication_response.py` — shape-contract regression.

### Removed

- `tools/kreditvakt_engine.py` — entire 320-line fabrication generator
  **deleted**. `_company_name_from_orgnr`, `_pick_score`, `_generate`, etc.
  no longer exist. If a test needs a fixture, add it to `tests/fixtures/`.
- `scoring/kreditvakt.py:_mock_fallback()` — entire function deleted.
- `server.py:_score_with_live_fallback()` — entire function deleted.
- All `from tools.kreditvakt_engine import score_company` lines (5 sites
  across `server.py` + `scoring/kreditvakt.py`) — gone.

### Operational fact at deploy time — read this

`norric_entities` is **empty (0 rows) in production today.** After this PR
ships, `/api/score/{orgnr}` will return HTTP 404 `orgnr_not_ingested` for
**every** orgnr, including ones the customer has previously been able to
query. This is the intended honest answer — the visible gap is what makes
the next ingestion priority visible — but it IS a hard cliff for any
current consumer of the score endpoint. Populating `norric_entities` from
Bolagsverket bulk is the next blocker before external outreach.

### Out of scope (tracked follow-ups)

- **`norric_entities` backfill from Bolagsverket bulk.** Required before
  any prospect demo or external API consumer can get a 200 from
  `/api/score/{orgnr}`. Separate PR.
- HTTP-level regression test (TestClient against a seeded test DB for the
  IKEA / H&M / Telia case) requires a `tests/conftest.py` Postgres fixture
  that doesn't exist yet. Function-boundary regression in
  `tests/test_no_fabrication_response.py` covers the contract for now.
- `signals[].label` strings remain in Swedish. Consistent with the
  rest of the per-signal payload; move to per-locale labels alongside any
  future `labels.sv` envelope work.
