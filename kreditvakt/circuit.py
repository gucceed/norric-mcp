"""
In-memory circuit breaker for the Kreditvakt scoring DB path.

States:
  CLOSED    — normal; failures counted.
  OPEN      — tripped; requests fail immediately for `open_duration_s`.
  HALF_OPEN — one trial request allowed; success → CLOSED, failure → OPEN.

Thresholds (configurable, defaults match spec 3.3):
  failure_threshold = 5 consecutive failures → OPEN
  open_duration_s   = 30 s in OPEN → HALF_OPEN
"""
from __future__ import annotations

import threading
import time
import logging

log = logging.getLogger(__name__)

CLOSED    = "closed"
OPEN      = "open"
HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, open_duration_s: float = 30.0):
        self._lock              = threading.Lock()
        self._state             = CLOSED
        self._consecutive_fails = 0
        self._opened_at: float  = 0.0
        self._threshold         = failure_threshold
        self._duration          = open_duration_s

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                if time.monotonic() - self._opened_at >= self._duration:
                    self._state = HALF_OPEN
                    log.info("[circuit:scoring] → HALF_OPEN — allowing trial request")
                    return True
                return False
            # HALF_OPEN — allow exactly one trial
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state != CLOSED:
                log.info("[circuit:scoring] → CLOSED — trial succeeded")
            self._state = CLOSED
            self._consecutive_fails = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_fails += 1
            if self._state == HALF_OPEN:
                self._state = OPEN
                self._opened_at = time.monotonic()
                log.warning("[circuit:scoring] → OPEN — trial failed, re-opening for %ds", self._duration)
            elif self._consecutive_fails >= self._threshold:
                self._state = OPEN
                self._opened_at = time.monotonic()
                log.warning(
                    "[circuit:scoring] → OPEN — %d consecutive failures, blocking for %ds",
                    self._consecutive_fails, self._duration,
                )


# Module-level singleton — shared across requests in this process instance.
scoring_circuit = CircuitBreaker(failure_threshold=5, open_duration_s=30.0)
