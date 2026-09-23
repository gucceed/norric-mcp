# Estonia country five prep - e-Ariregister open data

## Official source

- Open-data portal: https://avaandmed.ariregister.rik.ee/en/downloading-open-data
- API services overview: https://avaandmed.ariregister.rik.ee/en/open-data-api/introduction-api-services
- Daily bulk used here: `GET https://avaandmed.ariregister.rik.ee/sites/default/files/avaandmed/ettevotja_rekvisiidid__yldandmed.json.zip`
- Basic-data CSV alternative: `.../ettevotja_rekvisiidid__lihtandmed.csv.zip`

Eight open-data datasets (basic data, general data, registry cards, persons,
shareholders, beneficial owners, commercial pledges, rulings, annual reports)
are published as JSON/XML/CSV, updated once a day, under **CC BY 4.0**
(https://creativecommons.org/licenses/by/4.0/legalcode - linked from the portal
as "License information"). No key or account is needed; downloading accepts the
licence. Files only contain entities currently in the register (statuses:
entered into the register, in liquidation, in bankruptcy).

The real-time interface is the legacy **SOAP/XML v6** service
(https://ariregxmlv6.rik.ee/?wsdl). It needs a signed contract with RIK (free of
charge, applications reviewed within five working days), caps at 50,000
query-answers/day and 1 simultaneous query. It is out of scope for the
baseline; the daily snapshot is diffed locally like Finland.

## Scope and traps

This phase mirrors business identity, names, legal form, registry status,
registrations, address, main EMTAK activity, website (WWW contact entry only)
and source timestamps. It does not collect email/phone contact entries, people,
roles, shareholders or beneficial owners.

- Beneficial owners ARE published as an open bulk dataset in Estonia (unlike
  Denmark/Finland). They are still personal data and excluded from this mirror
  until Edgar explicitly opts in.
- Personal identification codes were removed from all open-data files on
  2024-11-01 for data-protection reasons.
- There is no keyless delta endpoint. Daily full snapshots are diffed locally.
  First seen by Norric is never reported as legal registration.
- Source dates are DD.MM.YYYY; country codes are ISO-3 (`EST`). Codes and
  Estonian labels are retained from the source. Unknown mappings stay null/raw
  rather than being invented.

## Residency

The only production upstream is `avaandmed.ariregister.rik.ee`; workers,
storage, logs, cache and backups must remain in approved EU regions. No data
load starts before the Stockholm database cutover. The migration and beat entry
are inert until the approved general worker and database are explicitly updated.

## Paid tools (wired in the follow-up build PR, not this prep branch)

- `estonian_company_verify_v1`, lookup band ($0.002), HTTP `/x402/ee/company/verify`
- `estonian_company_changes_v1`, feed-batch band ($0.02), HTTP `/x402/ee/company/changes`

## Post-Stockholm first-load runbook

Do not run this until the Stockholm database flip is independently confirmed
and the Finland baseline has completed successfully. Set `DATABASE_URL` to the
confirmed Stockholm database and pass its exact hostname as the guard:

```bash
python3 scripts/run_ee_post_stockholm_load.py \
  --confirm STOCKHOLM_FLIP_CONFIRMED_AND_FI_LOAD_FINISHED \
  --expected-db-host "$STOCKHOLM_DB_HOST"
```

The command applies the idempotent `EE_001` migration, verifies the schema, and
runs only `ariregister_bulk`. It does not start scheduling. After success,
verify `norric_pipeline_runs.pipeline='ariregister_bulk'` is `success`, the
entity count is non-zero, and `norric_ee_ingest_state.last_bulk_at` is set.
