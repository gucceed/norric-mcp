"""Stage 0 contract for Norric's immutable entity-event ledger.

This module is deliberately side-effect free. Stage 0 defines and tests the
wire/storage contract only; no beat imports it and no production path changes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

EVENT_TYPES = frozenset(
    {
        "entity.address.changed",
        "entity.officer.added",
        "entity.officer.removed",
        "entity.capital.changed",
        "entity.filing.added",
        "entity.bankruptcy.changed",
        "entity.score.changed",
        "entity.layoff_notice.changed",
    }
)

SOURCE_NAMES = frozenset(
    {
        "bolagsverket_bulk",
        "bolagsverket_konkurs",
        "kreditvakt_scoring",
        "arbetsformedlingen_varsel",
    }
)


def canonical_json(value: Any) -> str:
    """Return deterministic JSON used for evidence and idempotency hashes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def evidence_hash(evidence: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()


def idempotency_key(
    *,
    source: str,
    entity_key: str,
    event_type: str,
    source_observed_at: datetime,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> str:
    """Stable key: replays of the same observed mutation collapse to one row."""
    payload = {
        "source": source,
        "entity_key": entity_key,
        "event_type": event_type,
        "source_observed_at": _utc_iso(source_observed_at),
        "before": before,
        "after": after,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EntityEvent:
    entity_key: str
    entity_type: str
    event_type: str
    source: str
    source_observed_at: datetime
    detected_at: datetime
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    changed_fields: tuple[str, ...]
    evidence: Mapping[str, Any]
    detector_version: str

    def validate(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {self.event_type}")
        if self.source not in SOURCE_NAMES:
            raise ValueError(f"unsupported source: {self.source}")
        if not self.entity_key or not self.entity_type:
            raise ValueError("entity_key and entity_type are required")
        if not self.changed_fields:
            raise ValueError("changed_fields cannot be empty")
        if self.before == self.after:
            raise ValueError("before and after must differ")
        _utc_iso(self.source_observed_at)
        _utc_iso(self.detected_at)

    def hashes(self) -> tuple[str, str]:
        self.validate()
        return (
            evidence_hash(self.evidence),
            idempotency_key(
                source=self.source,
                entity_key=self.entity_key,
                event_type=self.event_type,
                source_observed_at=self.source_observed_at,
                before=self.before,
                after=self.after,
            ),
        )
