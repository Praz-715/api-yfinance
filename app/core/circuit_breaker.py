"""A minimal, coroutine-safe circuit breaker.

Protects upstream calls from cascading failures: once a target has failed
``failure_threshold`` times consecutively, the breaker *opens* and short-circuits
further calls for ``reset_seconds``. After that cool-down it enters a *half-open*
state allowing a single trial call to decide whether to close again.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum

from app.core.logging import get_logger

logger = get_logger("circuit_breaker")


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted while the breaker is open."""


class CircuitBreaker:
    """Per-target circuit breaker with monotonic-clock cool-down."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self._failure_threshold = max(1, failure_threshold)
        self._reset_seconds = max(1.0, reset_seconds)
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BreakerState:
        return self._state

    async def allow(self) -> bool:
        """Return ``True`` if a call may proceed, transitioning state as needed."""
        async with self._lock:
            if self._state is BreakerState.OPEN:
                if time.monotonic() - self._opened_at >= self._reset_seconds:
                    self._state = BreakerState.HALF_OPEN
                    logger.info("circuit_half_open", extra={"breaker": self.name})
                    return True
                return False
            return True

    async def record_success(self) -> None:
        async with self._lock:
            if self._state is not BreakerState.CLOSED:
                logger.info("circuit_closed", extra={"breaker": self.name})
            self._failures = 0
            self._state = BreakerState.CLOSED

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if (
                self._state is BreakerState.HALF_OPEN
                or self._failures >= self._failure_threshold
            ):
                self._state = BreakerState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit_opened",
                    extra={"breaker": self.name, "failures": self._failures},
                )
