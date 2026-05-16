# apier@bolagsverket.se — draft

**To:** apier@bolagsverket.se
**From:** edgar.mutebi1@gmail.com (or hej@norric.io)
**Subject:** Frågor om kodlista för bolagsverket_bulkfil — fält `pagandeAvvecklingsEllerOmstruktureringsforfarande`
**Send:** Edgar manually, after a final read-through.

---

Hej,

Norric AB använder den fria nedladdningsfilen `bolagsverket_bulkfil.zip` ([nedladdningsbara filer](https://bolagsverket.se/apierochoppnadata/nedladdningsbarafiler.2517.html)) som datakälla för konkursrelaterade händelser i vår tjänst Kreditvakt (företagsbevakning). Vi följer kodlistan som beskrivs på sidan "Detaljerad beskrivning av filens struktur och innehåll" och har en konkret fråga om fältet `pagandeAvvecklingsEllerOmstruktureringsforfarande` (fält 7 i bulkfilen).

**Vad vi har observerat**

Vid en fullständig genomgång av filen från 2026-05-11 (cirka 2,95 miljoner rader) hittade vi 18 unika koder i fält 7. 11 av dessa finns i kodlistan, avsnitt 3:

```
AC-AVOMFO, DEOL-AVOMFO, DEOT-AVOMFO, FR-AVOMFO, FUOL-AVOMFO,
FUOT-AVOMFO, GROM-AVOMFO, KK-AVOMFO, LI-AVOMFO, OM-AVOMFO, RES-AVOMFO
```

Övriga 8 koder förekommer i filen men ser inte ut att finnas dokumenterade i kodlistan. De följer mönstret `<grundkod>+<modifierare>+-AVSLAVOMFO`:

| Kod | Antal förekomster i 2026-05-11-filen |
|---|---:|
| `FRUHOR-AVSLAVOMFO` | 4 492 |
| `KKAVOV-AVSLAVOMFO` | 2 031 |
| `LIUHOR-AVSLAVOMFO` | 1 565 |
| `ACUHOR-AVSLAVOMFO` | 842 |
| `KKUHAVD-AVSLAVOMFO` | 609 |
| `LIUHAVD-AVSLAVOMFO` | 140 |
| `ACUHAVD-AVSLAVOMFO` | 24 |
| `FRUHAVD-AVSLAVOMFO` | 3 |

**Våra frågor**

1. Är dessa 8 koder dokumenterade någonstans (annan kodlista, teknisk specifikation, PDF) som vi har missat? Om ja, kan ni länka dokumentet?

2. Vår tolkning av mönstret, baserad på empirisk observation, är:
   - Grundkoderna `KK`, `LI`, `AC`, `FR` motsvarar konkurs, likvidation, ackordsförhandling och företagsrekonstruktion (per kodlistan avsnitt 3).
   - Modifierare `UHOR` ≈ "under hörande, avslutad", `UHAVD` ≈ "upphävd avdömt", `AVOV` ≈ "avslutat övrigt".
   - Suffix `-AVSLAVOMFO` indikerar att förfarandet har avslutats.
   
   Stämmer denna tolkning, och i så fall vilken är den korrekta officiella benämningen för varje kod?

3. Finns det andra koder som teoretiskt kan förekomma i fält 6 (`avregistreringsorsak`) eller fält 7 (`pagandeAvvecklingsEllerOmstruktureringsforfarande`) utöver de vi har observerat? Vi vill kunna hantera nya koder framåtblickande utan att tappa data.

4. Hur ofta uppdateras `bolagsverket_bulkfil.zip`? Vår observation (filer från 2026-05-04 och 2026-05-11, båda tidiga måndagar) tyder på veckovis kadens, men vi vill verifiera detta för att kunna planera vår ingestion-cron korrekt.

Tack på förhand. Vi är gärna behjälpliga med ytterligare empiriska data ur filen om det underlättar.

Med vänlig hälsning,
Edgar Mutebi
Grundare, Norric AB
norric.io · hej@norric.io

---

## English version (if preferred)

Hi,

Norric AB uses the free `bolagsverket_bulkfil.zip` download as a data source for konkurs-related events in our company-watch service Kreditvakt. We follow the kodlista described in the "Detaljerad beskrivning av filens struktur och innehåll" section of the [downloadable files page](https://bolagsverket.se/apierochoppnadata/nedladdningsbarafiler.2517.html), and we have a specific question about field 7 (`pagandeAvvecklingsEllerOmstruktureringsforfarande`).

**What we observed**

In a full scan of the 2026-05-11 file (~2.95 million rows), we found 18 distinct codes in field 7. Eleven of them appear in section 3 of the kodlista. The remaining eight do not, but all follow a consistent `<base>+<modifier>+-AVSLAVOMFO` pattern:

[same table as above]

**Our questions**

1. Are these eight codes documented anywhere we may have missed (a separate kodlista, a technical specification PDF)? If so, please point us at it.

2. Based on the naming pattern, our empirical reading is that these are resolution-state variants of the base initiation codes (`UHOR` ≈ concluded under hearing, `UHAVD` ≈ overturned by court, `AVOV` ≈ concluded "övrigt"). Is this correct, and what are the authoritative Swedish descriptions for each?

3. Are there other codes that might appear in field 6 (`avregistreringsorsak`) or field 7 (`pagandeAvvecklingsEllerOmstruktureringsforfarande`) beyond the 17 + 18 we have observed? We want to handle new codes forward-compatibly without dropping data.

4. What is the update cadence of `bolagsverket_bulkfil.zip`? Our observation (files dated 2026-05-04 and 2026-05-11, both early Monday) suggests a weekly cadence, but we want to confirm before scheduling our daily ingestion job.

Thank you. Happy to share additional empirical observations from the file if useful.

Best regards,
Edgar Mutebi
Founder, Norric AB
norric.io · hej@norric.io

---

## Notes for Edgar

- **Tone:** professional, neutral, technically specific. Treats Bolagsverket as a peer service-provider, not a vendor.
- **What it does NOT do:** ask for free API access, special favours, or PR. Pure documentation request.
- **Why send:** converts 8 known-unknowns into documented-knowns within ~1 business week. Unblocks the future "Insolvency Index methodology" page on norric.io/pulse and removes the `TODO(apier-reply)` in `konkurs_parser.py`.
- **When their reply lands:** update `RESOLVED_PROCEEDING_CODES` descriptions in `konkurs_parser.py`, flip `documentation_status` on the 8 codes from `'empirical'` → `'documented'` via one UPDATE on `norric_payment_signals`, archive the reply at `reference/apier_reply_<date>.eml`.
- **Update query when reply lands:**
  ```sql
  UPDATE norric_payment_signals
  SET raw_data = jsonb_set(raw_data, '{documentation_status}', '"documented"')
  WHERE raw_data->>'documentation_status' = 'empirical';
  ```
