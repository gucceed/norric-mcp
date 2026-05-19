# No-fabrication contract

## Core invariant — non-negotiable

For any request to a Kreditvakt scoring endpoint authenticated with a valid
key, the response contains **only data sourced from real DB rows**. If real
data doesn't exist, return a structured error. Never a fabricated number,
name, signal, or timestamp. Mock data is a test fixture, not a fallback.

## Hard rules

- No code under `scoring/`, `kreditvakt/`, or `mcp_tools/` may import, call,
  or define a function that generates fabricated company data.
- All fabrication helpers live under `tests/fixtures/` or `scripts/dev_*`
  and are unimportable from production modules.
- Removing the mock branch is a **one-way door**. Do not add a feature flag,
  env var, or kill-switch to re-enable it. If staging needs deterministic
  data, staging gets its own seeded DB, not a runtime mock.
- The legacy `score_source = 'mock'` value is removed from the response
  schema entirely. It cannot be a valid value of that field anywhere.

## Coverage commitment vs current state

`norric_entities` membership encodes *"have we committed to keeping this
entity fresh"*. Signal presence (rows in `norric_tax_signals`,
`norric_payment_signals`, etc.) encodes *"what do we know about it today"*.
Those are different questions and they map to different response classes:

| State | HTTP | `score_source` |
|---|---|---|
| Malformed orgnr / personnummer-shaped | 400 | n/a |
| Invalid / expired API key | 401 | n/a |
| Well-formed orgnr, not in `norric_entities` | 404 | n/a |
| In `norric_entities`, no current signals | 200 | `no_signals` |
| In `norric_entities`, signals present | 200 | `live` |

A deregistered (avregistrerade) company stays in `norric_entities` and
returns 200 — with `entity.status = "deregistered"` and `entity.deregistered_at`
populated. Portfolio monitoring loops never silently drop entities the
customer still wants visibility on.

## Field-family contract

| Field | Type | Range / Vocab | Polarity |
|---|---|---|---|
| `risk_score` | int \| null | 0–20 | ascending = worse |
| `risk_band` | int \| null | 1–5 | ascending = worse |
| `risk_tier` | string \| null | `HEALTHY`, `WATCH`, `ELEVATED`, `HIGH`, `CRITICAL` | enum, ascending = worse |
| `distress_probability` | float \| null | 0.0–1.0 | ascending = worse |
| `scale` | string (const) | `"0-20"` | metadata |
| `polarity` | string (const) | `"ascending_risk"` | metadata |
| `score_source` | string | `live` \| `no_signals` | metadata |

The `risk_` prefix is intentional. Nordic credit-scoring conventions
(UC, Creditsafe, FICO) ship a field where higher = healthier. Norric's
0–20 scale runs the opposite direction. The word "risk" in the field name
encodes direction; the explicit `polarity: ascending_risk` is a defensive
second signal for integrators who skip the docs.

## Personnummer / enskild firma boundary

Personnummer-shaped orgnrs (10 digits whose first 6 form a valid date
`YYMMDD` with MM 01-12 and DD 01-31 or 61-91) are rejected at the API
boundary with HTTP 400 before any DB lookup. The KuL exposure profile for
natural persons is structurally different from juridiska personer. Making
the API mechanically incapable of returning data on personnummer is a
cleaner regulatory posture than relying on downstream filters.

## Guardrail tests

- [`tests/test_no_fabrication_imports.py`](../tests/test_no_fabrication_imports.py)
  walks `scoring/`, `kreditvakt/`, `mcp_tools/` AST and fails if any
  forbidden import name (`faker`, `Faker`, `fabricate`, `score_company`,
  `tools.kreditvakt_engine`, etc.) appears. It also fails on any literal
  `"score_source": "mock"` runtime assignment in those directories.
- [`tests/test_no_fabrication_response.py`](../tests/test_no_fabrication_response.py)
  pins the no-signals contract at the function boundary: `score_source`
  must be `"no_signals"` (never `"mock"`), no `company_name`/`industry`
  fabrication leaks, `risk_tier` vocabulary matches the locked enum, the
  0–20 risk_score is ascending per band.

Both must pass in CI. Failing either blocks deploy.
