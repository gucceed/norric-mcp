# France country six prep - Sirene open data

## Official source

- Bulk dataset: https://www.data.gouv.fr/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret
  (`StockUniteLegale` legal units, `StockEtablissement` establishments; monthly
  stock files, CSV or parquet)
- Keyless search API: https://recherche-entreprises.api.gouv.fr/docs/
  (7 req/s per IP, no account; excludes non-diffusible units)
- Account-gated INSEE API Sirene V3.11: https://api.insee.fr (free account,
  30 calls/min; not required for the baseline)
- Insolvency follow-up: BODACC open data + API (DILA) -
  https://www.bodacc.fr/pages/donnees-ouvertes-et-api/ (procedures collectives;
  not part of this prep branch)

All Sirene data is under **Licence Ouverte / Open Licence 2.0** (Etalab).
The stock files and the search API need no key or account.

## Scope and traps

This phase mirrors legal-unit identity, denomination, legal-form code (INSEE
categories juridiques), administrative state, creation date, APE/NAF activity
code, siege-establishment address and source timestamps. It does not collect
people, roles, financials or beneficial owners.

- **Non-diffusible units are never mirrored.** Under Art. A123-96 of the code
  de commerce a natural person (entreprise individuelle) can opt out of
  commercial redistribution; rows whose `statutDiffusionUniteLegale` is not `O`
  are dropped at ingest. This is a legal-reuse constraint, not a filter we can
  relax without Edgar's decision.
- Legal-form and activity codes are stored as official codes; labels stay null
  until an official INSEE nomenclature file is wired in. No invented mappings.
- The stock CSV is monthly; the keyless search API is fresh but rate-limited
  and search-only. Daily diffs of consecutive stock files drive the changes
  feed. First seen by Norric is never reported as legal registration.
- Sirene carries no website field. The search API complements identity only.

## Residency

Production upstreams are `static.data.gouv.fr` and
`recherche-entreprises.api.gouv.fr` (both French state infrastructure);
workers, storage, logs, cache and backups must remain in approved EU regions.
No data load starts before the Stockholm database cutover. The migration and
beat entry are inert until the approved general worker and database are
explicitly updated.

## Paid tools (wired in the follow-up build PR, not this prep branch)

- `french_company_verify_v1`, lookup band ($0.002), HTTP `/x402/fr/company/verify`
- `french_company_changes_v1`, feed-batch band ($0.02), HTTP `/x402/fr/company/changes`

## Post-Stockholm first-load runbook

Do not run this until the Stockholm database flip is independently confirmed
and the Estonia baseline has completed successfully. Set `DATABASE_URL` to the
confirmed Stockholm database and pass its exact hostname as the guard:

```bash
python3 scripts/run_fr_post_stockholm_load.py \
  --confirm STOCKHOLM_FLIP_CONFIRMED_AND_EE_LOAD_FINISHED \
  --expected-db-host "$STOCKHOLM_DB_HOST"
```

The command applies the idempotent `FR_001` migration, verifies the schema, and
runs only `sirene_bulk` (legal units, then siege addresses). It does not start
scheduling. After success, verify `norric_pipeline_runs.pipeline='sirene_bulk'`
is `success`, the entity count is non-zero, and
`norric_fr_ingest_state.last_bulk_at` is set.
