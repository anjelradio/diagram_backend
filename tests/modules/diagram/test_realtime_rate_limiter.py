from app.modules.diagram.infrastructure.realtime.rate_limiter import CursorRateLimiter


def test_rate_limiter_drops_messages_after_burst_then_refills() -> None:
    limiter = CursorRateLimiter(rate=30, burst=2)
    assert limiter.allow(now=0)
    assert limiter.allow(now=0)
    assert not limiter.allow(now=0)
    assert limiter.allow(now=1 / 30)
