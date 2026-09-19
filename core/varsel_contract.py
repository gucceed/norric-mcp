"""Stage 0 matching and validation contract for varsel notices.

No source client or scoring path is included. This module only defines which
joins may be automatic and which must remain in review.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

AUTO_MATCH_METHODS = frozenset({"exact_orgnr"})
REVIEW_MATCH_METHODS = frozenset({"normalised_name", "name_and_address"})


@dataclass(frozen=True)
class VarselMatch:
    notice_ref: str
    notice_date: date
    company_key: str | None
    match_method: str
    confidence: float
    affected_count_min: int | None = None
    affected_count_max: int | None = None

    def validate(self) -> None:
        if self.match_method not in AUTO_MATCH_METHODS | REVIEW_MATCH_METHODS | {"unmatched"}:
            raise ValueError(f"unsupported match_method: {self.match_method}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.match_method == "exact_orgnr" and not self.company_key:
            raise ValueError("exact_orgnr requires company_key")
        if self.affected_count_min is not None and self.affected_count_min < 0:
            raise ValueError("affected_count_min cannot be negative")
        if self.affected_count_max is not None and self.affected_count_max < 0:
            raise ValueError("affected_count_max cannot be negative")
        if None not in (self.affected_count_min, self.affected_count_max):
            if self.affected_count_min > self.affected_count_max:
                raise ValueError("affected count range is inverted")

    @property
    def can_auto_score(self) -> bool:
        self.validate()
        return self.match_method in AUTO_MATCH_METHODS and self.confidence == 1.0
