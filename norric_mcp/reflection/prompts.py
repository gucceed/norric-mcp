"""
norric_mcp/reflection/prompts.py

Reflection node judge prompts for Kreditvakt score report evaluation.

The judge verifies that a generated score narrative is internally consistent,
correctly scaled, and factually grounded — before the report reaches the customer.

Band table is hardcoded here so the judge has the canonical source and cannot
invent thresholds. If scoring/display.py bands change, update this table too.
"""

# ── Canonical Kreditvakt risk band table ──────────────────────────────────────
#
# Source of truth: scoring/display.py  _BAND_LABELS / _BAND_ACTIONS / _BAND_BOUNDARIES
# distress_probability thresholds: [0.20, 0.40, 0.60, 0.80]
# display_score formula: round(distress_probability * 20), clamped to [0, 20]
#
# Band | Label            | display_score | Prescribed action
# -----|------------------|---------------|--------------------------------------------------
#  1   | Stabil           |  0 – 3        | Inga åtgärder krävs.
#  2   | Bevaka           |  4 – 7        | Monitorera kvartalsvis. Förstärk inte krediten
#      |                  |               | utan ny utvärdering.
#  3   | Förhöjd risk     |  8 – 11       | Begränsa nya kreditlinjer. Begär uppdaterade
#      |                  |               | ekonomiska underlag.
#  4   | Kräv säkerhet    | 12 – 15       | Befintliga relationer endast med personlig borgen
#      |                  |               | eller fakturapant. Stoppa nya kreditlinjer.
#  5   | Stoppa krediter  | 16 – 20       | Akut. Stoppa utgående krediter. Påbörja
#      |                  |               | indrivning. Konkurs sannolik inom 90 dagar.

_BAND_TABLE = """
| Band | Label            | display_score | Prescribed action                                                                                                          |
|------|------------------|---------------|----------------------------------------------------------------------------------------------------------------------------|
|  1   | Stabil           |  0 – 3        | Inga åtgärder krävs.                                                                                                       |
|  2   | Bevaka           |  4 – 7        | Monitorera kvartalsvis. Förstärk inte krediten utan ny utvärdering.                                                        |
|  3   | Förhöjd risk     |  8 – 11       | Begränsa nya kreditlinjer. Begär uppdaterade ekonomiska underlag.                                                          |
|  4   | Kräv säkerhet    | 12 – 15       | Befintliga relationer endast med personlig borgen eller fakturapant. Stoppa nya kreditlinjer.                               |
|  5   | Stoppa krediter  | 16 – 20       | Akut. Stoppa utgående krediter. Påbörja indrivning. Konkurs sannolik inom 90 dagar.                                        |
"""


# ── Judge prompt ──────────────────────────────────────────────────────────────

SCORE_REPORT_JUDGE_PROMPT = """\
You are a quality-control judge for Kreditvakt score reports. Your task is to
evaluate a generated narrative against three independent checks. Return a
structured verdict for each check.

## Input you will receive

- `display_score`: integer 0–20
- `band`: integer 1–5
- `band_label`: string (one of: Stabil, Bevaka, Förhöjd risk, Kräv säkerhet, Stoppa krediter)
- `band_action`: string (the prescribed action for this band, from the table below)
- `narrative`: the generated report text to evaluate

## Canonical band table

Use this table as the sole authority on band boundaries, labels, and prescribed
actions. Do not infer, interpolate, or invent bands outside this table.

{band_table}

## Check 1 — SCALE_CORRECTNESS

Verify that every numeric reference in the narrative is consistent with the
reported display_score and band.

Pass criteria:
- If the narrative states a score, it must match display_score exactly.
- If the narrative implies a severity level (e.g. "low risk", "critical"), it
  must be consistent with the band number (band 1–2 = low; band 3 = elevated;
  band 4–5 = high/critical).
- The narrative must not quote a score from a different scale (e.g. 0–100
  insolvency_score as if it were the 0–20 display_score).

Fail examples:
- display_score=14, band=4, but narrative says "the company scores 14 out of
  100" — scale confusion.
- display_score=3, band=1, but narrative describes "significant distress" —
  severity inconsistency.

## Check 2 — SCORE_NARRATIVE_CONSISTENCY

Verify that the narrative tone and recommendations match the prescribed band
action. The band action is the authoritative instruction for this risk level.

Pass criteria:
- Band 5 (Stoppa krediter, score 16–20): narrative MUST contain urgency language
  and credit-stoppage recommendation. Phrases like "monitor" or "review next
  quarter" are a fail for band 5.
- Band 4 (Kräv säkerhet, score 12–15): narrative MUST recommend collateral,
  personal guarantee, or stopping new credit lines. Reassuring language is a
  fail for band 4.
- Band 3 (Förhöjd risk, score 8–11): narrative MUST recommend limiting new
  credit and requesting updated financials. Unconditional approval language is
  a fail for band 3.
- Band 2 (Bevaka, score 4–7): narrative MUST recommend quarterly monitoring.
  Alarm language is a fail for band 2.
- Band 1 (Stabil, score 0–3): narrative MUST be reassuring. Urgent or
  restrictive language is a fail for band 1.

A mismatch between band action and narrative tone is always a fail, regardless
of whether the score number appears correctly.

## Check 3 — FACTUAL_GROUNDING

Verify that every factual claim in the narrative is supported by the signal
data provided.

Pass criteria:
- Every specific debt amount, creditor name, date, or case reference cited in
  the narrative must appear in the input signals.
- The narrative must not fabricate creditor names, amounts, or dates not present
  in the signals.
- Hedging language ("may indicate", "suggests") is acceptable for inferences,
  but direct assertions must be traceable to a signal.

Fail examples:
- Narrative cites "Kronofogden case KFM-2024-44821" when no such case appears
  in the signals.
- Narrative states "tax debt of 450 000 kr" when signals show 312 400 kr.

## Output format

Return JSON with this exact structure:

{{
  "scale_correctness": {{
    "pass": true | false,
    "finding": "<one sentence — what was checked and what was found>"
  }},
  "score_narrative_consistency": {{
    "pass": true | false,
    "finding": "<one sentence — which band action was required and whether the narrative satisfied it>"
  }},
  "factual_grounding": {{
    "pass": true | false,
    "finding": "<one sentence — any unsupported claims, or confirmation that all claims are grounded>"
  }},
  "overall": "pass" | "fail",
  "blocking_issues": ["<issue 1>", "<issue 2>"]
}}

`overall` is "pass" only if all three checks pass. `blocking_issues` lists each
failed check as a short actionable string. If all pass, `blocking_issues` is [].

Do not add commentary outside the JSON object.
"""


def build_judge_prompt(
    display_score: int,
    band: int,
    band_label: str,
    band_action: str,
    narrative: str,
) -> str:
    """Return the fully-rendered judge prompt for a score report."""
    return (
        SCORE_REPORT_JUDGE_PROMPT.format(band_table=_BAND_TABLE)
        + f"\n## Report to evaluate\n\n"
        + f"display_score: {display_score}\n"
        + f"band: {band}\n"
        + f"band_label: {band_label}\n"
        + f"band_action: {band_action}\n\n"
        + f"narrative:\n{narrative}\n"
    )
