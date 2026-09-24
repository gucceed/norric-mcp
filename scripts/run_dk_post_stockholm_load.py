#!/usr/bin/env python3
"""Paced one-shot DK baseline into the Stockholm database.

Fail-closed: exact Stockholm host plus the chain confirmation string, then
the migration, then a paced bulk load. Scheduling stays with the beat entry.
See scripts/_nordic_post_stockholm.py and docs/nordic-post-stockholm-loads.md.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._nordic_post_stockholm import DK, _safe_target, run  # noqa: E402,F401

CONFIRMATION = DK.confirmation


def main() -> None:
    run(DK)


if __name__ == "__main__":
    main()
