#!/usr/bin/env python3
"""Estimate compact event payload bytes from representative synthetic mutations.

This does not estimate Postgres indexes/WAL. Use the documented Stockholm
rehearsal query before approving the migration.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.event_contract import canonical_json

SAMPLES = [
    {
        "entity_key": "5561234567", "entity_type": "company",
        "event_type": "entity.address.changed", "source": "bolagsverket_bulk",
        "source_observed_at": "2026-09-19T01:00:00Z", "detected_at": "2026-09-19T03:10:00Z",
        "before": {"address": "Gamla gatan 1, 111 11 Stockholm"},
        "after": {"address": "Nya gatan 2, 112 22 Stockholm"},
        "changed_fields": ["address"], "evidence_hash": "a" * 64, "detector_version": "stage0.v1",
    },
    {
        "entity_key": "5561234567", "entity_type": "company",
        "event_type": "entity.officer.added", "source": "bolagsverket_bulk",
        "source_observed_at": "2026-09-19T01:00:00Z", "detected_at": "2026-09-19T03:10:00Z",
        "before": None, "after": {"role": "board_member", "person_key": "person_3f69b2d1"},
        "changed_fields": ["officers"], "evidence_hash": "b" * 64, "detector_version": "stage0.v1",
    },
    {
        "entity_key": "5567654321", "entity_type": "company",
        "event_type": "entity.score.changed", "source": "kreditvakt_scoring",
        "source_observed_at": "2026-09-19T03:30:00Z", "detected_at": "2026-09-19T05:31:00Z",
        "before": {"risk_band": 2, "distress_probability": 0.18},
        "after": {"risk_band": 4, "distress_probability": 0.67},
        "changed_fields": ["risk_band", "distress_probability"],
        "evidence_hash": "c" * 64, "detector_version": "stage0.v1",
    },
    {
        "entity_key": "5567654321", "entity_type": "company",
        "event_type": "entity.bankruptcy.changed", "source": "bolagsverket_konkurs",
        "source_observed_at": "2026-09-19T04:00:00Z", "detected_at": "2026-09-19T04:16:00Z",
        "before": {"status": "active"}, "after": {"status": "bankrupt", "case_ref": "K-2026-1042"},
        "changed_fields": ["bankruptcy.status"], "evidence_hash": "d" * 64, "detector_version": "stage0.v1",
    },
]


def sample_bytes() -> list[int]:
    return [len(canonical_json(item).encode("utf-8")) for item in SAMPLES]


def main() -> None:
    sizes = sample_bytes()
    average = mean(sizes)
    print(json.dumps({
        "sample_count": len(sizes),
        "payload_bytes": sizes,
        "average_payload_bytes": round(average, 1),
        "projected_payload_gib_per_million_events": round(average * 1_000_000 / 1024**3, 3),
        "excludes": ["Postgres row overhead", "indexes", "WAL", "backups"],
    }, indent=2))

if __name__ == "__main__":
    main()
