-- T1-05: Lantmäteriet property registry

CREATE TABLE IF NOT EXISTS norric_properties (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fastighet_id         text UNIQUE,
    fastighetsbeteckning text,
    kommunkod            text,
    county               text,
    orgnr                text,
    owner_name           text,
    building_year        integer,
    taxeringsvarde_sek   bigint,
    area_sqm             numeric,
    coordinates_lat      numeric,
    coordinates_lon      numeric,
    source               text NOT NULL,
    licence_required     boolean NOT NULL DEFAULT false,
    last_updated_at      timestamptz DEFAULT now(),
    created_at           timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_properties_kommunkod ON norric_properties(kommunkod);
CREATE INDEX IF NOT EXISTS idx_properties_orgnr     ON norric_properties(orgnr);
CREATE INDEX IF NOT EXISTS idx_properties_fastighet ON norric_properties(fastighetsbeteckning text_pattern_ops);
