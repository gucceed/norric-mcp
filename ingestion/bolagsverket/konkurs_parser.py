"""
Bolagsverket konkurs parser.

Streams `bolagsverket_bulkfil.txt` line by line, extracts konkurs-related events
from field 6 (`avregistreringsorsak`) and field 7
(`pagandeAvvecklingsEllerOmstruktureringsforfarande`), and yields one record
per (orgnr, konkurs filing).

Source for all code dictionaries:
  norric-mcp/ingestion/bolagsverket/reference/nedladdningsbara_filer.html
  ("Detaljerad beskrivning av filens struktur och innehåll" → sections 1–5)
  Cached locally as kodlista_extracted.json. Retrieved 2026-05-14 from
  https://bolagsverket.se/apierochoppnadata/nedladdningsbarafiler.2517.html
  via Playwright.

Code system note:
  The bulk file uses ALPHABETIC mnemonic codes (KK-AVOMFO, KKAV-AVORG, …).
  Näringslivsregistret's statuskoder.pdf uses a DIFFERENT NUMERIC system
  (20 = "Konkurs inledd", 21 = "Konkurs avslutad", …). These two vocabularies
  are not interchangeable. ALPHABETIC_TO_NUMERIC_MAPPING below bridges them
  semantically (by Swedish description match) for downstream display use.

Column layout in bolagsverket_bulkfil.txt (0-indexed, semicolon-delimited):
  0: organisationsidentitet          (orgnr$ORGNR-IDORG)
  1: namnskyddslopnummer             ('1' primary / '2' alternate)
  2: registreringsland               (SE-LAND)
  3: organisationsnamn               (name$FORETAGSNAMN-ORGNAM$YYYY-MM-DD)
  4: organisationsform               (AB-ORGFO, BRF-ORGFO, …)
  5: avregistreringsdatum            (YYYY-MM-DD or empty)
  6: avregistreringsorsak            (KKAV-AVORG, VERKUPP-AVORG, …)
  7: pagandeAvvecklingsEllerOmstruktureringsforfarande
                                     (|CODE$YYYY-MM-DD|CODE$YYYY-MM-DD …)
  8: registreringsdatum
  9: verksamhetsbeskrivning
 10: postadress                      (street$co$city$postcode$SE-LAND)

Sub-delimiter inside fields: $
Event repeater inside field 7: |

PRE-EXISTING BUG NOTE
  ingestion/bolagsverket/bulk_parser.py reads row[1] as "name", but field 1
  is namnskyddslopnummer (the name-protection sequence number). Actual name
  is in field 3. This parser uses field 3 correctly.
"""
from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Optional, TextIO

log = logging.getLogger(__name__)


# ── Locked configuration (Edgar 2026-05-13/14) ────────────────────────────────

DEFAULT_ORG_FORMS: frozenset[str] = frozenset({"AB-ORGFO", "BRF-ORGFO"})
"""
Default scope. Configurable per-call so adding HB-ORGFO / KB-ORGFO / EK-ORGFO
later is a config change, not a code change.
"""

DEFAULT_BACKFILL_MONTHS: int = 24
"""
Hard cutoff on filed_at. Events older than this are skipped at parse time.

TODO(pulse-insolvency-index): When Norric Pulse Insolvency Index needs deeper
baseline coverage, split the full history into `norric_payment_signals_archive`
rather than expanding this cutoff. The hot path (Kreditvakt /score) only reads
the trailing 365 days; loading 40+ years inline would dilute that read.
"""


# ── ORG_FORMS (kodlista section 1, all 29 codes) ──────────────────────────────

ORG_FORMS: dict[str, str] = {
    "AB-ORGFO":   "Aktiebolag",
    "BAB-ORGFO":  "Bankaktiebolag",
    "BF-ORGFO":   "Bostadsförening",
    "BFL-ORGFO":  "Utländsk banks filial",
    "BRF-ORGFO":  "Bostadsrättsförening",
    "E-ORGFO":    "Enskild näringsverksamhet",
    "EB-ORGFO":   "Enkla bolag",
    "EEIG-ORGFO": "Europeisk ekonomisk intressegruppering",
    "EGTS-ORGFO": "Europeisk gruppering för territoriellt samarbete",
    "EK-ORGFO":   "Ekonomisk förening",
    "FAB-ORGFO":  "Försäkringsaktiebolag",
    "FF-ORGFO":   "Försäkringsförmedlare",
    "FL-ORGFO":   "Filial",
    "FOF-ORGFO":  "Försäkringsförening",
    "HB-ORGFO":   "Handelsbolag",
    "I-ORGFO":    "Ideell förening som bedriver näringsverksamhet",
    "KB-ORGFO":   "Kommanditbolag",
    "KHF-ORGFO":  "Kooperativ hyresrättsförening",
    "MB-ORGFO":   "Medlemsbank",
    "OFB-ORGFO":  "Ömsesidigt försäkringsbolag",
    "OTPB-ORGFO": "Ömsesidigt tjänstepensionsbolag",
    "S-ORGFO":    "Stiftelse som bedriver näringsverksamhet",
    "SB-ORGFO":   "Sparbank",
    "SCE-ORGFO":  "Europakooperativ",
    "SE-ORGFO":   "Europabolag",
    "SF-ORGFO":   "Sambruksförening",
    "TPAB-ORGFO": "Tjänstepensionsaktiebolag",
    "TPF-ORGFO":  "Tjänstepensionsförening",
    "TSF-ORGFO":  "Trossamfund som bedriver näringsverksamhet",
}


# ── DEREG_REASON_CODES (kodlista section 2, all 17 codes — field 6) ───────────

DEREG_REASON_CODES: dict[str, str] = {
    "AKEJH-AVORG":    "Aktiekapitalet inte höjts",
    "ARSEED-AVORG":   "Årsredovisning saknas",
    "AVREG-AVORG":    "Avregistrerad",
    "BABAKEJH-AVORG": "Ombildat till bankaktiebolag eller aktiekapitalet inte höjts",
    "DELAV-AVORG":    "Delning",
    "DOM-AVORG":      "Beslut av instans",
    "FUAV-AVORG":     "Fusion",
    "GROMAV-AVORG":   "Gränsöverskridande ombildning",
    "KKAV-AVORG":     "Konkurs",
    "LIAV-AVORG":     "Likvidation",
    "NYINN-AVORG":    "Ny innehavare",
    "OMAV-AVORG":     "Ombildning",
    "OMBAB-AVORG":    "Ombildat till bankaktiebolag",
    "OVERK-AVORG":    "Overksamhet",
    "UTLKKLI-AVORG":  "Det utländska företagets likvidation eller konkurs",
    "VDSAK-AVORG":    "Verkställande direktör saknas",
    "VERKUPP-AVORG":  "Verksamheten har upphört",
}


# ── ACTIVE_PROCEEDING_CODES (kodlista section 3, all 11 base codes — field 7) ─

ACTIVE_PROCEEDING_CODES: dict[str, str] = {
    "AC-AVOMFO":   "Ackordsförhandling",
    "DEOL-AVOMFO": "Överlåtande vid delning",
    "DEOT-AVOMFO": "Övertagande vid delning",
    "FR-AVOMFO":   "Företagsrekonstruktion",
    "FUOL-AVOMFO": "Överlåtande i fusion",
    "FUOT-AVOMFO": "Övertagande i fusion",
    "GROM-AVOMFO": "Gränsöverskridande ombildning",
    "KK-AVOMFO":   "Konkurs",
    "LI-AVOMFO":   "Likvidation",
    "OM-AVOMFO":   "Ombildning",
    "RES-AVOMFO":  "Resolution",
}


# ── RESOLVED_PROCEEDING_CODES (observed empirically — UNDOCUMENTED in kodlista)
#
# These eight `*-AVSLAVOMFO` suffix variants appear in the bulk file but are
# NOT listed in the official kodlista. Meaning inferred from the Bolagsverket
# naming convention: <base procedure>+<modifier infix>+'-AVSLAVOMFO'.
# Modifier infixes: AVOV (avslutat övrigt), UHOR (under hörande),
# UHAVD (upphävd avdömt). Coverage verified against 2,953,887-row scan.
# TODO(apier-reply): Update descriptions when Bolagsverket apier@ replies.

RESOLVED_PROCEEDING_CODES: dict[str, str] = {
    "KKAVOV-AVSLAVOMFO":  "Konkurs avslutad övrigt (med överskott)",       # 2,031 obs
    "KKUHAVD-AVSLAVOMFO": "Konkurs upphävd av rätt (avdömt)",              #   609 obs
    "LIUHOR-AVSLAVOMFO":  "Likvidation avslutad under hörande",            # 1,565 obs
    "LIUHAVD-AVSLAVOMFO": "Likvidation upphävd av rätt (avdömt)",          #   140 obs
    "ACUHOR-AVSLAVOMFO":  "Ackordsförhandling avslutad under hörande",     #   842 obs
    "ACUHAVD-AVSLAVOMFO": "Ackordsförhandling upphävd av rätt (avdömt)",   #    24 obs
    "FRUHOR-AVSLAVOMFO":  "Företagsrekonstruktion avslutad under hörande", # 4,492 obs
    "FRUHAVD-AVSLAVOMFO": "Företagsrekonstruktion upphävd av domstol",     #     3 obs
}


# ── Signal categories for Kreditvakt scorer ───────────────────────────────────
#
# Groups codes by their distress-signal meaning. The scorer reads /score from
# these categories rather than raw codes, so changes to Bolagsverket's
# vocabulary localise here.

KONKURS_SIGNAL_CATEGORIES: dict[str, frozenset[str]] = {
    "KONKURS_FILED": frozenset({
        "KK-AVOMFO",          # konkurs inledd (currently in konkurs)
        "KKAV-AVORG",         # konkurs avslutad → deregistered (historical)
        "KKAVOV-AVSLAVOMFO",  # konkurs avslutad övrigt (concluded with overskott)
    }),
    "KONKURS_REVERSED": frozenset({
        "KKUHAVD-AVSLAVOMFO",  # konkurs upphävd av rätt
    }),
    "EARLY_WARNING": frozenset({
        "AC-AVOMFO",   # ackordsförhandling pågående
        "FR-AVOMFO",   # företagsrekonstruktion pågående
        "RES-AVOMFO",  # resolution pågående (bank/finance)
    }),
    "DISTRESS_RESOLVED": frozenset({
        "ACUHOR-AVSLAVOMFO",   # ackord avslutad
        "ACUHAVD-AVSLAVOMFO",  # ackord upphävd av rätt
        "FRUHOR-AVSLAVOMFO",   # företagsrekonstruktion avslutad
        "FRUHAVD-AVSLAVOMFO",  # företagsrekonstruktion upphävd av domstol
    }),
}


# ── ALPHABETIC_TO_NUMERIC_MAPPING (bulk-file → statuskoder.pdf) ───────────────

ALPHABETIC_TO_NUMERIC_MAPPING: dict[str, str] = {
    # Konkurs lifecycle
    "KK-AVOMFO":          "20",  # Konkurs inledd
    "KKAV-AVORG":         "21",  # Konkurs avslutad
    "KKAVOV-AVSLAVOMFO":  "22",  # Konkurs avslutad med överskott
    "KKUHAVD-AVSLAVOMFO": "24",  # Konkurs upphävd av rätt
    # Ackord
    "AC-AVOMFO":          "11",  # Ackordsförhandling inledd
    "ACUHOR-AVSLAVOMFO":  "12",  # Ackordsförhandling upphör
    "ACUHAVD-AVSLAVOMFO": "13",  # Ackordsförhandling upphävd av rätt
    # Företagsrekonstruktion
    "FR-AVOMFO":          "80",
    "FRUHOR-AVSLAVOMFO":  "81",
    "FRUHAVD-AVSLAVOMFO": "82",
    # Resolution
    "RES-AVOMFO":         "85",
}


# ── Konkurs-relevant code subsets ─────────────────────────────────────────────

_KONKURS_INITIATION_CODES: frozenset[str] = frozenset({"KK-AVOMFO"})
_KONKURS_RESOLUTION_CODES_FIELD7: frozenset[str] = frozenset({
    "KKAVOV-AVSLAVOMFO", "KKUHAVD-AVSLAVOMFO",
})
_KONKURS_DEREG_REASON_CODE: str = "KKAV-AVORG"

# All codes Bolagsverket documents officially (sections 2 + 3 of the kodlista).
# Used for the "unmapped code" log line per megaprompt Phase 4.2 requirement.
_DOCUMENTED_CODES: frozenset[str] = frozenset(
    set(DEREG_REASON_CODES) | set(ACTIVE_PROCEEDING_CODES)
)


# ── Field extraction helpers ──────────────────────────────────────────────────


def _extract_orgnr(id_field: str) -> Optional[str]:
    """'5560004615$ORGNR-IDORG' → '5560004615'. Returns None if malformed."""
    raw = id_field.split("$", 1)[0].strip().replace("-", "").replace(" ", "")
    return raw if len(raw) == 10 and raw.isdigit() else None


def _extract_primary_name(name_field: str) -> str:
    """
    Strip type-tag and date subfields; return the human-readable name.
    'BRF Källan 1$FORETAGSNAMN-ORGNAM$2015-05-08' → 'BRF Källan 1'
    """
    primary = name_field.split("|", 1)[0]
    return primary.split("$", 1)[0].strip()


def _parse_field7_events(raw: str) -> list[tuple[str, date]]:
    """
    Parse the pagandeAvvecklingsEllerOmstruktureringsforfarande field into a
    list of (event_code, event_date) tuples, oldest first.

    Field format: '|CODE1$YYYY-MM-DD|CODE2$YYYY-MM-DD'  (pipe-prefixed, repeats)
    Empty field → empty list. Malformed events are skipped, not raised.
    """
    events: list[tuple[str, date]] = []
    if not raw:
        return events
    for chunk in raw.lstrip("|").split("|"):
        if "$" not in chunk:
            continue
        code, _, date_str = chunk.partition("$")
        try:
            event_date = date.fromisoformat(date_str.strip())
        except ValueError:
            continue
        events.append((code.strip(), event_date))
    events.sort(key=lambda x: x[1])
    return events


def _default_cutoff() -> date:
    """24 months prior to today — month-exact math to avoid leap-year drift."""
    today = date.today()
    y, m = today.year, today.month - DEFAULT_BACKFILL_MONTHS
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(today.day, 28))


def _documentation_status(code: str) -> str:
    """
    Returns 'documented' if the code is in the official kodlista (sections 2/3),
    'empirical' if it's an observed-but-undocumented suffix variant.

    Per Edgar 2026-05-14: queryable tag so future audits can find empirical
    codes programmatically via `raw_data->>'documentation_status' = 'empirical'`.
    Flip to 'documented' in a single UPDATE when apier@ replies or Bolagsverket
    publishes a kodlista revision.
    """
    if code in _DOCUMENTED_CODES:
        return "documented"
    if code in RESOLVED_PROCEEDING_CODES:
        return "empirical"
    return "unknown"


# ── Record builder ────────────────────────────────────────────────────────────


def _build_record(
    orgnr: str,
    name: str,
    orgform: str,
    filed_at: date,
    status_code: str,
    resolved_at: Optional[date],
    event_history: list[tuple[str, date]],
) -> dict:
    """
    Assemble one output record for the writer.

    case_ref is f'bv-konkurs-{orgnr}-{filed_at.isoformat()}' — stable across
    the filing lifecycle. UNIQUE INDEX on (orgnr, case_ref) lets the writer
    ON CONFLICT update status_code, resolved_at, and is_active when a
    previously-pending filing concludes.

    raw_data.signal_type MUST be 'konkurs' — scoring/kreditvakt.py:99-108
    filters on `raw_data->>'signal_type' = 'konkurs'`.
    """
    is_resolved = resolved_at is not None
    # Scorer normalises orgnr to DASHED format before querying
    # (scoring/kreditvakt.py:66-68). Store dashed form so queries match.
    # case_ref uses the no-dash form for a clean internal filing identifier.
    orgnr_dashed = f"{orgnr[:6]}-{orgnr[6:]}"
    return {
        "orgnr":         orgnr_dashed,
        "orgnr_display": orgnr_dashed,
        "case_ref":      f"bv-konkurs-{orgnr}-{filed_at.isoformat()}",
        "status_code":   status_code,
        "filed_at":      filed_at,
        "resolved_at":   resolved_at,
        "is_active":     not is_resolved,
        "raw_data": {
            "signal_type":          "konkurs",
            "creditor_type":        "bolagsverket_konkurs",
            "orgform":              orgform,
            "name":                 name,
            "status_numeric":       ALPHABETIC_TO_NUMERIC_MAPPING.get(status_code),
            "documentation_status": _documentation_status(status_code),
            "event_history": [
                {"code": code, "date": d.isoformat()}
                for code, d in event_history
            ],
        },
    }


# ── Streaming helpers ─────────────────────────────────────────────────────────


def _strip_nuls(stream: TextIO) -> Iterable[str]:
    """
    csv.reader chokes on NUL bytes; the bulk file occasionally contains stray
    NULs. Strip them at the line layer.
    """
    for line in stream:
        if "\x00" in line:
            yield line.replace("\x00", "")
        else:
            yield line


# ── Public API ────────────────────────────────────────────────────────────────


def parse_konkurs_events(
    path: Path,
    org_forms: Optional[Iterable[str]] = None,
    cutoff_date: Optional[date] = None,
) -> Iterator[dict]:
    """
    Yield one dict per (orgnr, konkurs-initiation-event) found in the bulk file.

    Per row, may produce:
      - Zero records if no konkurs events in field 7 and no KKAV-AVORG in field 6.
      - One record per KK-AVOMFO event in field 7. Matching KKAVOV-AVSLAVOMFO
        or KKUHAVD-AVSLAVOMFO events (later date, same row) are attached as
        resolved_at + status_code.
      - One synthetic record for KKAV-AVORG in field 6 (using avregistreringsdatum
        as filed_at) when the company was deregistered specifically due to konkurs
        and no field-7 KK-AVOMFO event covers it. Historical-coverage case.

    Args:
      path:        Path to the unzipped bolagsverket_bulkfil.txt.
      org_forms:   Filter set for field 4. Default = DEFAULT_ORG_FORMS.
      cutoff_date: Skip events with filed_at < cutoff_date. Default = today - 24mo.
    """
    org_forms_set = frozenset(org_forms or DEFAULT_ORG_FORMS)
    cutoff = cutoff_date or _default_cutoff()
    unmapped_codes: set[str] = set()

    log.info(
        "parse_konkurs_events: path=%s org_forms=%s cutoff=%s",
        path, sorted(org_forms_set), cutoff,
    )

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(_strip_nuls(f), delimiter=";", quotechar='"')
        for line_no, row in enumerate(reader, start=1):
            if line_no == 1:
                continue  # header
            if len(row) < 11:
                continue

            # Field 4: org form filter
            orgform = row[4].strip()
            if orgform not in org_forms_set:
                continue

            # Field 0: orgnr
            orgnr = _extract_orgnr(row[0])
            if not orgnr:
                continue

            # Field 3: name (correct field — NOT row[1] which is sequence number)
            name = _extract_primary_name(row[3])
            # Field 5: avregistreringsdatum (deregistration date)
            dereg_str = row[5].strip()
            dereg_date: Optional[date] = None
            if dereg_str:
                try:
                    dereg_date = date.fromisoformat(dereg_str)
                except ValueError:
                    pass
            # Field 6: avregistreringsorsak
            dereg_reason = row[6].strip()
            # Field 7: pagandeAvvecklingsEllerOmstruktureringsforfarande
            events = _parse_field7_events(row[7])

            # Surface unmapped codes once each (logged at end of file)
            for code, _ in events:
                if (code not in ACTIVE_PROCEEDING_CODES
                        and code not in RESOLVED_PROCEEDING_CODES):
                    unmapped_codes.add(code)

            # ── Path A: field-7 KK-AVOMFO events (active or concluded konkurs) ──
            kk_initiations = [(c, d) for c, d in events if c == "KK-AVOMFO"]
            kk_resolutions = [
                (c, d) for c, d in events if c in _KONKURS_RESOLUTION_CODES_FIELD7
            ]

            emitted_for_dates: set[date] = set()
            for _, filed_at in kk_initiations:
                if filed_at < cutoff:
                    continue
                # Find earliest resolution event after this initiation
                resolution = next(
                    ((c, d) for c, d in sorted(kk_resolutions, key=lambda x: x[1])
                     if d >= filed_at),
                    None,
                )
                status_code = resolution[0] if resolution else "KK-AVOMFO"
                resolved_at = resolution[1] if resolution else None

                yield _build_record(
                    orgnr=orgnr,
                    name=name,
                    orgform=orgform,
                    filed_at=filed_at,
                    status_code=status_code,
                    resolved_at=resolved_at,
                    event_history=events,
                )
                emitted_for_dates.add(filed_at)

            # ── Path B: field-6 KKAV-AVORG (deregistered due to konkurs) ──
            # Only synthesise if there was no field-7 KK-AVOMFO record already
            # emitted for this orgnr (avoid double-counting same filing).
            if (dereg_reason == _KONKURS_DEREG_REASON_CODE
                    and dereg_date is not None
                    and dereg_date >= cutoff
                    and not emitted_for_dates):
                yield _build_record(
                    orgnr=orgnr,
                    name=name,
                    orgform=orgform,
                    filed_at=dereg_date,
                    status_code="KKAV-AVORG",
                    resolved_at=dereg_date,  # already concluded by definition
                    event_history=events,
                )

    if unmapped_codes:
        log.warning(
            "konkurs_parser observed %d unmapped field-7 codes (not in "
            "ACTIVE_PROCEEDING_CODES ∪ RESOLVED_PROCEEDING_CODES): %s",
            len(unmapped_codes), sorted(unmapped_codes),
        )
