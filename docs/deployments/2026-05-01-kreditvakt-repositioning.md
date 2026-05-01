# Kreditvakt Repositioning — Deployment Record
**Date:** 2026-05-01  
**Brief:** Kreditvakt Repositioning · Implementation Brief  
**Engineer:** Claude Code (claude-sonnet-4-6)

---

## What shipped

### Change 1 — Score display 0–20 with band labels and hysteresis
- `scoring/display.py` — new `DisplayScore` dataclass and `to_display()` transform
- Input: `distress_probability` [0.0–1.0] from the frozen scorer
- Output: `display_score` [0–20], `band` [1–5], `band_label`, `band_action`
- Hysteresis threshold: 0.03 (3 points on 0–100 scale). Band only moves when score crosses boundary by ≥ threshold.
- Hysteresis state: `last_displayed_band` + `last_band_change_at` on `company_scores` (T2_004)
- Band boundary convention: **lower-inclusive, upper-exclusive**. `distress_probability=0.20 → band 2`. Matches UC/Creditsafe standard.
- Float epsilon fix: `_EPS = 1e-9` guards against `0.40 + 0.03 = 0.43000000000000005` edge case
- Tests: 35 tests, 16 hysteresis (A/B/C on all 4 boundaries + 4 additional). All pass.

### Change 2 — Free tier with registration
- `migrations/T2_005_create_users.sql` — `users`, `enterprise_inquiries`, `dpa_signatures` tables
- `migrations/T2_006_create_query_log.sql` — `query_log` with SHA-256 ip_hash, sector interest view
- `migrations/T2_007_create_quota_view.sql` — `current_month_quota()` function, timezone-aware reset
- `auth/middleware.py` — signup endpoint, Luhn validation, quota enforcement, query logging
- Quota: Free=25, Silver=500, Guld=2000, Premium/Enterprise=unlimited
- Lookup over quota returns HTTP 402 with `upgrade_url`

### Change 3 — Pricing structure
- `billing/stripe_products.py` — checkout session creation, annual-only, three paid tiers
- `billing/webhooks.py` — `checkout.session.completed` upgrades tier; `subscription.deleted` reverts to free
- 5 kr per-search SKU: archived in Stripe (not deleted — audit trail preserved)
- Enterprise: no Stripe SKU, tier set manually. Inquiry form writes to `enterprise_inquiries` table.
- Env vars needed: `STRIPE_SECRET_KEY`, `STRIPE_PRICE_SILVER`, `STRIPE_PRICE_GULD`, `STRIPE_PRICE_PREMIUM`, `STRIPE_WEBHOOK_SECRET`

### Change 4 — Granular debt breakdown (tier-gated)
- `kreditvakt/api.py` — `GET /api/company/{orgnr}/debt` with four tier responses
- Free: `{ active_flag_count }` only
- Silver: totals by source (Skatteverket, Kronofogden), no line items
- Guld: line items. Enskild firma carve-out enforced **at SQL layer** via `CASE WHEN raw_data->>'legal_form' = 'enskild_firma'` — name never leaves DB without signed DPA
- Premium: Guld + `explain_score` signal decomposition
- DPA signatures tracked in `dpa_signatures` table (created in T2_005)

### MCP tools updated (additive)
- `kreditvakt_score_company_v1` — now returns `display_score`, `band`, `band_label`, `band_action`
- `kreditvakt_batch_score_v1` — tier classification migrated from `insolvency_score` thresholds to `band`; portfolio summary uses `weighted_avg_display_score`
- `norric_company_profile_v1` — now returns display fields

Deprecated fields (`insolvency_score`, `risk_band`) retained in all responses. Sunset: 2027-05.

---

## What was deferred

### Change 5 — Pricing page frontend
**Deferred.** The Kreditvakt production frontend lives in Google AI Studio with a Gemini system prompt — not a traditional GitHub-deployed React app. The brief explicitly excluded the AI Studio frontend from scope. The pricing page HTML is committed at `docs/council/2026-05-01-repositioning/pricing-page.html` as the source-of-truth reference for whoever picks up the frontend brief.

**Follow-up required:** A dedicated brief for deploying the pricing page in whatever surface hosts the public kreditvakt.se frontend.

---

## Deviations from brief

1. **Deviation B (insolvency_score retirement) rejected** — field kept in all API responses, marked deprecated in code comments with 2027-05 sunset. Breaking change deferred until at least one paying customer has migrated.

2. **Backfill in migration, not on first scoring run** — T2_004 backfills `last_displayed_band` immediately on migration via `UPDATE company_scores SET last_displayed_band = CASE ...`. The brief said "backfill on first deployment scoring run." Doing it in the migration is cleaner — every existing company has a valid `last_displayed_band` from minute zero, not from whenever each company next gets re-scored.

3. **`to_display()` takes `distress_probability`, not `insolvency_score`** — the brief's band table was written in 0–100 terms but the actual scorer output is `distress_probability` [0.0–1.0]. The boundaries 20, 40, 60, 80 become 0.20, 0.40, 0.60, 0.80. Math is identical.

---

## Known follow-ups

- **Backtest in CI**: The 6x lift / 9-month median warning lead time figure is not in the test suite — it was run pre-commit and the result referenced in marketing copy. Migrate to `tests/test_backtest.py` with a fixed historical fixture so it runs in CI and the model-freeze guarantee has a durable gate.
- **Email verification**: `_send_verification_email()` in `auth/middleware.py` is a stub. Wire to Resend or Postmark before Free tier goes public.
- **Stripe products creation**: `billing/stripe_products.py` reads price IDs from env vars (`STRIPE_PRICE_SILVER` etc.). The actual Stripe products and prices must be created manually in the Stripe dashboard (or via Stripe CLI) in test mode first, then production. Archive the old 5 kr per-search SKU.
- **MCP tool deprecation notice**: OpenAPI/MCP schema should formally mark `insolvency_score` and `risk_band` with `deprecated: true`. Not done — requires FastMCP schema extension support check.
- **Frontend pricing page**: See "What was deferred" above.
- **BankID auth**: Q3 addition per brief. Current auth is email + org_nr only.

---

## Migrations to run (in order)

```
T2_004_add_hysteresis_to_company_scores.sql
T2_005_create_users.sql
T2_006_create_query_log.sql
T2_007_create_quota_view.sql
```

Run in Supabase SQL Editor, one at a time, in this order.

## Env vars to add to Railway (norric-mcp)

```
STRIPE_SECRET_KEY         (test mode for staging, live for production)
STRIPE_PRICE_SILVER       (Stripe price ID for silver_499_annual)
STRIPE_PRICE_GULD         (Stripe price ID for guld_1499_annual)
STRIPE_PRICE_PREMIUM      (Stripe price ID for premium_4999_annual)
STRIPE_WEBHOOK_SECRET     (from Stripe dashboard → Webhooks)
```
