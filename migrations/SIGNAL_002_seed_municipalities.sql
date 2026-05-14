-- ============================================================
-- SIGNAL_002_seed_municipalities.sql
-- Run AFTER SIGNAL_001_core_tables.sql
-- Idempotent — safe to run multiple times
-- ============================================================

INSERT INTO municipalities (id, name, region, county_code, platform, scrape_url, active)
VALUES
    (180,  'Stockholm',    'Stockholm',       '01', 'lex',       'https://www.stockholm.se/',     true),
    (162,  'Danderyd',     'Stockholm',       '01', 'lex',       'https://www.danderyd.se/',      true),
    (163,  'Järfälla',     'Stockholm',       '01', 'lex',       'https://www.jarfalla.se/',      true),
    (181,  'Södertälje',   'Stockholm',       '01', 'evolution', 'https://www.sodertalje.se/',    true),
    (182,  'Nacka',        'Stockholm',       '01', 'lex',       'https://www.nacka.se/',         true),
    (183,  'Sundbyberg',   'Stockholm',       '01', 'lex',       'https://www.sundbyberg.se/',    true),
    (184,  'Solna',        'Stockholm',       '01', 'lex',       'https://www.solna.se/',         true),
    (186,  'Lidingö',      'Stockholm',       '01', 'lex',       'https://www.lidingo.se/',       true),
    (188,  'Norrtälje',    'Stockholm',       '01', 'lex',       'https://www.norrtalje.se/',     true),
    (380,  'Uppsala',      'Uppsala',         '03', 'evolution', 'https://www.uppsala.se/',       true),
    (381,  'Enköping',     'Uppsala',         '03', 'lex',       'https://www.enkoping.se/',      true),
    (580,  'Linköping',    'Östergötland',    '05', 'evolution', 'https://www.linkoping.se/',     true),
    (581,  'Norrköping',   'Östergötland',    '05', 'evolution', 'https://www.norrkoping.se/',    true),
    (680,  'Jönköping',    'Jönköping',       '06', 'lex',       'https://www.jonkoping.se/',     true),
    (780,  'Växjö',        'Kronoberg',       '07', 'evolution', 'https://www.vaxjo.se/',         true),
    (880,  'Kalmar',       'Kalmar',          '08', 'lex',       'https://www.kalmar.se/',        true),
    (1280, 'Malmö',        'Skåne',           '12', 'lex',       'https://www.malmo.se/',         true),
    (1281, 'Lund',         'Skåne',           '12', 'lex',       'https://www.lund.se/',          true),
    (1282, 'Landskrona',   'Skåne',           '12', 'lex',       'https://www.landskrona.se/',    true),
    (1283, 'Helsingborg',  'Skåne',           '12', 'evolution', 'https://www.helsingborg.se/',   true),
    (1284, 'Höganäs',      'Skåne',           '12', 'lex',       'https://www.hoganas.se/',       true),
    (1285, 'Eslöv',        'Skåne',           '12', 'lex',       'https://www.eslov.se/',         true),
    (1286, 'Ystad',        'Skåne',           '12', 'lex',       'https://www.ystad.se/',         true),
    (1287, 'Trelleborg',   'Skåne',           '12', 'lex',       'https://www.trelleborg.se/',    true),
    (1290, 'Kristianstad', 'Skåne',           '12', 'evolution', 'https://www.kristianstad.se/',  true),
    (1291, 'Simrishamn',   'Skåne',           '12', 'lex',       'https://www.simrishamn.se/',    true),
    (1292, 'Ängelholm',    'Skåne',           '12', 'lex',       'https://www.angelholm.se/',     true),
    (1293, 'Hässleholm',   'Skåne',           '12', 'evolution', 'https://www.hassleholm.se/',    true),
    (1380, 'Halmstad',     'Halland',         '13', 'evolution', 'https://www.halmstad.se/',      true),
    (1381, 'Laholm',       'Halland',         '13', 'lex',       'https://www.laholm.se/',        true),
    (1382, 'Falkenberg',   'Halland',         '13', 'lex',       'https://www.falkenberg.se/',    true),
    (1383, 'Varberg',      'Halland',         '13', 'lex',       'https://www.varberg.se/',       true),
    (1384, 'Kungsbacka',   'Halland',         '13', 'evolution', 'https://www.kungsbacka.se/',    true),
    (1480, 'Göteborg',     'Västra Götaland', '14', 'evolution', 'https://www.goteborg.se/',      true),
    (1481, 'Mölndal',      'Västra Götaland', '14', 'evolution', 'https://www.molndal.se/',       true),
    (1482, 'Kungälv',      'Västra Götaland', '14', 'lex',       'https://www.kungalv.se/',       true),
    (1485, 'Uddevalla',    'Västra Götaland', '14', 'evolution', 'https://www.uddevalla.se/',     true),
    (1488, 'Trollhättan',  'Västra Götaland', '14', 'evolution', 'https://www.trollhattan.se/',   true),
    (1490, 'Borås',        'Västra Götaland', '14', 'evolution', 'https://www.boras.se/',         true),
    (1496, 'Skövde',       'Västra Götaland', '14', 'evolution', 'https://www.skovde.se/',        true),
    (1880, 'Örebro',       'Örebro',          '18', 'evolution', 'https://www.orebro.se/',        true),
    (1980, 'Västerås',     'Västmanland',     '19', 'evolution', 'https://www.vasteras.se/',      true),
    (2080, 'Falun',        'Dalarna',         '20', 'lex',       'https://www.falun.se/',         true),
    (2081, 'Borlänge',     'Dalarna',         '20', 'evolution', 'https://www.borlange.se/',      true),
    (2180, 'Gävle',        'Gävleborg',       '21', 'evolution', 'https://www.gavle.se/',         true),
    (2281, 'Sundsvall',    'Västernorrland',  '22', 'evolution', 'https://www.sundsvall.se/',     true),
    (2380, 'Östersund',    'Jämtland',        '23', 'lex',       'https://www.ostersund.se/',     true),
    (2480, 'Umeå',         'Västerbotten',    '24', 'evolution', 'https://www.umea.se/',          true),
    (2580, 'Luleå',        'Norrbotten',      '25', 'evolution', 'https://www.lulea.se/',         true),
    (2581, 'Piteå',        'Norrbotten',      '25', 'lex',       'https://www.pitea.se/',         true),
    (2584, 'Kiruna',       'Norrbotten',      '25', 'lex',       'https://www.kiruna.se/',        true)

ON CONFLICT (id) DO UPDATE SET
    name       = EXCLUDED.name,
    region     = EXCLUDED.region,
    platform   = EXCLUDED.platform,
    scrape_url = EXCLUDED.scrape_url,
    active     = EXCLUDED.active;

SELECT platform, COUNT(*) FROM municipalities GROUP BY platform ORDER BY COUNT(*) DESC;
