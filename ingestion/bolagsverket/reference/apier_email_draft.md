# Draft email to apier@bolagsverket.se

**To:** apier@bolagsverket.se
**From:** Edgar Mutebi <edgar@norric.io>
**Subject:** bolagsverket_bulkfil.zip — bekräftelse av kodvärden i fält 7

---

Hej,

Jag bygger en datapipeline mot Värdefulla datamängders bulkfil (bolagsverket_bulkfil.zip) och har en fråga om kodförteckningen i avsnitt 3 av filens dokumentation på https://bolagsverket.se/apierochoppnadata/nedladdningsbarafiler.2517.html

I dokumentationen listas 11 initieringskoder för fältet `pagandeAvvecklingsEllerOmstruktureringsforfarande` (AC-AVOMFO, FR-AVOMFO, KK-AVOMFO, LI-AVOMFO, RES-AVOMFO osv.).

Vid genomgång av en aktuell bulkfil (datum 2026-05-11, parsad mot 2 953 887 rader) observerar vi även 8 kodvarianter med suffix `-AVSLAVOMFO` som verkar markera **avslutning** av motsvarande förfarande:

| Observerad kod | Antal förekomster | Vår tolkning (att bekräftas) |
|---|---:|---|
| KKAVOV-AVSLAVOMFO  | 2 031 | Konkurs avslutad övrigt (med överskott?) |
| KKUHAVD-AVSLAVOMFO |   609 | Konkurs upphävd av rätt (avdömt) |
| LIUHOR-AVSLAVOMFO  | 1 565 | Likvidation avslutad under hörande |
| LIUHAVD-AVSLAVOMFO |   140 | Likvidation upphävd av rätt |
| ACUHOR-AVSLAVOMFO  |   842 | Ackordsförhandling avslutad under hörande |
| ACUHAVD-AVSLAVOMFO |    24 | Ackordsförhandling upphävd av rätt |
| FRUHOR-AVSLAVOMFO  | 4 492 | Företagsrekonstruktion avslutad under hörande |
| FRUHAVD-AVSLAVOMFO |     3 | Företagsrekonstruktion upphävd av domstol |

Två frågor:

1. **Stämmer tolkningen ovan?** Specifikt: betyder `KKAVOV-AVSLAVOMFO` "konkurs avslutad med överskott" (motsvarande Näringslivsregistrets numeriska statuskod 22)? Och betyder `KKUHAVD-AVSLAVOMFO` "konkurs upphävd av rätt" (motsvarande 24)?

2. **Finns det en officiell dokumentation av avslutskoderna** (eller motsvarande mappning till Näringslivsregistrets numeriska statuskoder per statuskoder.pdf) som inte är publicerad på sidan ovan? Det skulle hjälpa oss att låsa fast den juridiska semantiken innan vi exponerar signalen i en kredittjänst.

Tack på förhand,
Edgar Mutebi
Norric AB
edgar@norric.io
