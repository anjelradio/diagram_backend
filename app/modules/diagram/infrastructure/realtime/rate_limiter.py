"""Limitación ligera para eventos efímeros de alta frecuencia."""

import time


class CursorRateLimiter:
    """Token bucket por conexión; permite ráfagas pequeñas sin saturar la sala."""

    def __init__(self, rate: float = 75.0, burst: int = 75) -> None:
        self.rate = rate
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated_at = time.monotonic()

    def allow(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        elapsed = max(0.0, current - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated_at = current
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True
