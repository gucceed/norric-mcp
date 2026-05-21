-- ============================================================
-- SIGNAL_005_municipality_coords.sql
-- Municipality lat/lng centroids
--
-- Adds geographic anchor points to municipalities for visualisations
-- (blast-radius peer placement, stress-map heat, contagion network).
-- ~40 centroids seeded by name — covers the SIGNAL_002 scrape universe
-- minus the smaller Stockholm-area kommuner without distinct demo value.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, and UPDATE-by-name is a no-op
-- against rows already at the same value or absent from the table.
-- Names are unique across the SIGNAL_002 seed (verified) so each
-- UPDATE matches exactly zero or one row.
-- ============================================================

ALTER TABLE municipalities
    ADD COLUMN IF NOT EXISTS lat FLOAT,
    ADD COLUMN IF NOT EXISTS lng FLOAT;

-- ── Storstadsregioner ─────────────────────────────────────────
UPDATE municipalities SET lat = 59.334, lng = 18.063  WHERE name = 'Stockholm';
UPDATE municipalities SET lat = 57.707, lng = 11.967  WHERE name = 'Göteborg';
UPDATE municipalities SET lat = 55.605, lng = 13.003  WHERE name = 'Malmö';

-- ── Skåne ────────────────────────────────────────────────────
UPDATE municipalities SET lat = 55.705, lng = 13.191  WHERE name = 'Lund';
UPDATE municipalities SET lat = 56.046, lng = 12.694  WHERE name = 'Helsingborg';
UPDATE municipalities SET lat = 56.034, lng = 12.999  WHERE name = 'Landskrona';
UPDATE municipalities SET lat = 55.875, lng = 12.830  WHERE name = 'Höganäs';
UPDATE municipalities SET lat = 55.838, lng = 13.304  WHERE name = 'Eslöv';
UPDATE municipalities SET lat = 55.430, lng = 13.820  WHERE name = 'Ystad';
UPDATE municipalities SET lat = 55.375, lng = 13.157  WHERE name = 'Trelleborg';
UPDATE municipalities SET lat = 56.031, lng = 14.153  WHERE name = 'Kristianstad';
UPDATE municipalities SET lat = 55.557, lng = 14.297  WHERE name = 'Simrishamn';
UPDATE municipalities SET lat = 56.243, lng = 12.861  WHERE name = 'Ängelholm';
UPDATE municipalities SET lat = 56.159, lng = 13.766  WHERE name = 'Hässleholm';

-- ── Halland ──────────────────────────────────────────────────
UPDATE municipalities SET lat = 56.674, lng = 12.857  WHERE name = 'Halmstad';
UPDATE municipalities SET lat = 56.499, lng = 13.073  WHERE name = 'Laholm';
UPDATE municipalities SET lat = 56.905, lng = 12.489  WHERE name = 'Falkenberg';
UPDATE municipalities SET lat = 57.106, lng = 12.250  WHERE name = 'Varberg';
UPDATE municipalities SET lat = 57.483, lng = 12.073  WHERE name = 'Kungsbacka';

-- ── Västra Götaland ──────────────────────────────────────────
UPDATE municipalities SET lat = 57.656, lng = 12.014  WHERE name = 'Mölndal';
UPDATE municipalities SET lat = 57.871, lng = 11.974  WHERE name = 'Kungälv';
UPDATE municipalities SET lat = 58.352, lng = 11.917  WHERE name = 'Uddevalla';
UPDATE municipalities SET lat = 58.284, lng = 12.289  WHERE name = 'Trollhättan';
UPDATE municipalities SET lat = 57.721, lng = 12.940  WHERE name = 'Borås';
UPDATE municipalities SET lat = 58.389, lng = 13.845  WHERE name = 'Skövde';

-- ── Småland & Östergötland ───────────────────────────────────
UPDATE municipalities SET lat = 58.411, lng = 15.621  WHERE name = 'Linköping';
UPDATE municipalities SET lat = 57.783, lng = 14.162  WHERE name = 'Jönköping';
UPDATE municipalities SET lat = 56.879, lng = 14.809  WHERE name = 'Växjö';
UPDATE municipalities SET lat = 56.664, lng = 16.362  WHERE name = 'Kalmar';

-- ── Uppland / Mellansverige ──────────────────────────────────
UPDATE municipalities SET lat = 59.859, lng = 17.644  WHERE name = 'Uppsala';
UPDATE municipalities SET lat = 59.274, lng = 15.213  WHERE name = 'Örebro';
UPDATE municipalities SET lat = 59.611, lng = 16.544  WHERE name = 'Västerås';

-- ── Dalarna & Gävleborg ──────────────────────────────────────
UPDATE municipalities SET lat = 60.607, lng = 15.632  WHERE name = 'Falun';
UPDATE municipalities SET lat = 60.485, lng = 15.438  WHERE name = 'Borlänge';
UPDATE municipalities SET lat = 60.675, lng = 17.142  WHERE name = 'Gävle';

-- ── Norrland ─────────────────────────────────────────────────
UPDATE municipalities SET lat = 62.391, lng = 17.307  WHERE name = 'Sundsvall';
UPDATE municipalities SET lat = 63.178, lng = 14.637  WHERE name = 'Östersund';
UPDATE municipalities SET lat = 63.825, lng = 20.263  WHERE name = 'Umeå';
UPDATE municipalities SET lat = 65.584, lng = 22.155  WHERE name = 'Luleå';
UPDATE municipalities SET lat = 65.316, lng = 21.479  WHERE name = 'Piteå';
UPDATE municipalities SET lat = 67.855, lng = 20.226  WHERE name = 'Kiruna';

COMMENT ON COLUMN municipalities.lat IS
'Approximate municipal centroid latitude (WGS84). Used by intelligence '
'dashboard for blast-radius peer placement and stress-map heat overlays. '
'Seeded by SIGNAL_005; not maintained from Lantmäteriet.';

COMMENT ON COLUMN municipalities.lng IS
'Approximate municipal centroid longitude (WGS84). See lat comment.';
