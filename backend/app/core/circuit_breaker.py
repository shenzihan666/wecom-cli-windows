"""Tiny process-local circuit breaker for flaky external calls (AI server).

Philosophy: a dead AI server should not be hammered every poll cycle (each
call costs money and time). After ``threshold`` consecutive failures the
circuit opens for ``cooldown_sec``; the first call after that is a half-open
probe. A success resets the failure count.

State lives in-process for the lifetime of the poll-worker subprocess; that is
exactly the scope we want (one breaker per account worker). Thread-safety is
not required because ``process_once`` runs single-threaded in the worker.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    threshold: int = 3
    cooldown_sec: float = 120.0
    _failures: int = 0
    _opened_at: float = 0.0  # monotonic time when circuit opened; 0 == closed
    _name: str = ""

    @property
    def is_open(self) -> bool:
        """True if calls should be short-circuited right now."""
        if self._opened_at == 0.0:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_sec:
            # Cooldown elapsed: let exactly one probe call through (half-open).
            return False
        return True

    def record_success(self) -> None:
        if self._failures or self._opened_at:
            logger.info("[%s] circuit closed after recovery", self._name or "cb")
        self._failures = 0
        self._opened_at = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold and self._opened_at == 0.0:
            self._opened_at = time.monotonic()
            logger.warning(
                "[%s] circuit opened: %d consecutive failures, cooldown=%.0fs",
                self._name or "cb",
                self._failures,
                self.cooldown_sec,
            )

    def reset(self) -> None:
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        if self.is_open:
            return "open"
        if self._opened_at:
            return "half-open"
        return "closed"

    def snapshot(self) -> dict:
        return {
            "name": self._name,
            "state": self.state,
            "failures": self._failures,
            "threshold": self.threshold,
            "cooldown_sec": self.cooldown_sec,
        }


@dataclass
class CircuitBreakerRegistry:
    """Named breakers so each external dependency gets its own state."""

    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    def get(
        self,
        name: str,
        *,
        threshold: int = 3,
        cooldown_sec: float = 120.0,
    ) -> CircuitBreaker:
        cb = self._breakers.get(name)
        if cb is None:
            cb = CircuitBreaker(threshold=threshold, cooldown_sec=cooldown_sec)
            cb._name = name  # noqa: SLF001
            self._breakers[name] = cb
        return cb


# Process-wide singleton. In the poll worker this covers one account's lifetime.
breaker_registry = CircuitBreakerRegistry()
