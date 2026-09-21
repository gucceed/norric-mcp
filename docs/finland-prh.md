# Finland country four - PRH/YTJ open data

## Official source

- Open-data overview: https://www.prh.fi/en/companiesandorganisations/tietopalvelut/prhopendata.html
- API schema: https://avoindata.prh.fi/opendata-ytj-api/v3/schema?lang=en
- Daily bulk: `GET https://avoindata.prh.fi/opendata-ytj-api/v3/all_companies`
- Point/search API: `GET .../companies?businessId=...` or `?name=...`

PRH says the data are free of charge, usable in applications/services, digital,
and updated once a day. The API schema declares CC BY 4.0. No key or account is
needed. Search returns at most 100 records per page and documents HTTP 429 but no
numeric quota. The client uses the daily ZIP instead of paging the search API.

## Scope and traps

This phase mirrors business identity, names, legal form, company situations,
registrations, address, industry, website and source timestamps. It does not
collect phone/email, people, roles or beneficial owners.

- Beneficial owners are not open data. PRH says access is limited to Anti-Money
  Laundering Act purposes. Do not ingest or expose them.
- The public Tax Debt Register is a search service, not an open bulk/API feed.
  Company entries only say whether debt is at least EUR 10,000 or returns were
  neglected; sole traders require identification and searches are logged. It is
  excluded until PRH/Vero confirms an automated-reuse route.
- HILMA procurement and Tutkihankintoja spending are follow-up datasets. This
  registry PR does not scrape HILMA pages or mix procurement into identity data.
- There is no public delta endpoint in v3. Daily full snapshots are diffed locally.
  First seen by Norric is never reported as legal registration.
- Codes and multilingual labels are retained from the source. Unknown mappings
  stay null/raw rather than being invented.

## Residency

The only production upstream is `avoindata.prh.fi`; workers, storage, logs, cache
and backups must remain in approved EU regions. No data load starts before the
Stockholm database cutover. The migration and beat entry are inert until the
approved general worker and database are explicitly updated.

## Paid tools

- `finnish_company_verify_v1`, lookup band ($0.002), HTTP `/x402/fi/company/verify`
- `finnish_company_changes_v1`, feed-batch band ($0.02), HTTP `/x402/fi/company/changes`
