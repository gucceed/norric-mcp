-- Norric provenance records table
-- Migration 002 — matches NorricProvenance model in core/provenance.py
--
-- Run against Supabase: paste into SQL editor or use psql.
-- Idempotent: all statements use IF NOT EXISTS / DO NOTHING.

CREATE TABLE IF NOT EXISTS provenance_records (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           text NOT NULL,           -- orgnr, notice_id, building_id
    product             text NOT NULL,           -- kreditvakt | sigvik | signal | vigil
    agency              text NOT NULL,           -- bolagsverket | kronofogden | skatteverket | etc.
    fetched_at          timestamptz NOT NULL,
    source_url          text,
    confidence_tier     text NOT NULL,           -- direct | parsed | inferred | estimated
    raw_ref             text,                    -- canonical document reference (source_document_ref)
    -- Extended fields matching NorricProvenance model:
    source_agency       text NOT NULL,           -- Agency enum value or "kommun:{kommunkod}"
    source_document_ref text NOT NULL,           -- make_document_ref() output
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    confidence          numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    raw_url             text,
    schema_version      text NOT NULL DEFAULT '1.0',
    -- Tool name for provenance chain lookup:
    tool_name           text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provenance_entity     ON provenance_records(entity_id);
CREATE INDEX IF NOT EXISTS idx_provenance_product    ON provenance_records(product);
CREATE INDEX IF NOT EXISTS idx_provenance_fetched    ON provenance_records(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_provenance_agency     ON provenance_records(source_agency);
CREATE INDEX IF NOT EXISTS idx_provenance_entity_tool ON provenance_records(entity_id, tool_name);
CREATE INDEX IF NOT EXISTS idx_provenance_ingested   ON provenance_records(ingested_at DESC);
