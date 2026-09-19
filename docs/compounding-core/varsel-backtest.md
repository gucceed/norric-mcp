# Varsel Distress Index - Stage 0 validation contract

The product joins Arbetsförmedlingen layoff notices to Norric's company timeline and bankruptcy observations. The public data is not proprietary; the stable join, observed history and measured predictive lift are.

## Hypothesis, not a claim

The proposed signal may lead bankruptcy by roughly 3-6 months. Do not publish that horizon or add the signal to a customer score until a held-out study measures it.

## Join rules

| Match | Action |
|---|---|
| Exact canonical organisation number | Eligible for automated event emission and backtest |
| Normalised name only | Manual/review queue; never auto-score |
| Name plus address | Manual/review queue; never auto-score |
| No defensible match | Keep unmatched source evidence; do not attach to a company |

Every accepted match stores source notice identity, notice date, match method, resolver version and evidence hash. Organisation-number history must handle renamed or dissolved companies without rewriting past joins.

## Cohort design

1. Choose a historical training window and a later, untouched holdout window.
2. Include every company in registry coverage at the cohort start, not only bankruptcies.
3. Define outcomes from the bankruptcy feed with an outcome date and source evidence.
4. Measure lead windows at 30, 90, 180 and 365 days.
5. Compare the varsel signal alone and combined with the current Kreditvakt score.
6. Report precision, recall, false-positive rate, PR-AUC, calibration, median lead time and lift over baseline.
7. Break results out by company size, sector, geography and affected-count availability to expose bias and sparse-data artefacts.
8. Freeze the detector version before reading holdout outcomes.

## Production gate

Edgar chooses the acceptable lift and false-positive threshold after seeing the first held-out results. Until then:

- `entity.layoff_notice.changed` can exist as an evidence event;
- exact matches can be watched as raw notices;
- no combined distress score or 3-6 month prediction claim ships;
- all work stays branch/PR only and within the existing $30/month stop-gate.
