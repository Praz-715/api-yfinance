"""Per-client rate limiting built on SlowAPI.

The client is identified by the left-most address in ``X-Forwarded-For`` (set by
Vercel's edge) and falls back to the socket peer address. When ``REDIS_URL`` is
configured the limiter uses Redis as shared storage so limits hold across
serverless instances; otherwise it uses in-process storage.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings


def client_identifier(request: Request) -> str:
    """Resolve the rate-limit key for a request (real client IP)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # The first hop is the original client; subsequent hops are proxies.
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return get_remote_address(request)


def build_limiter() -> Limiter:
    """Construct the application limiter from settings."""
    settings = get_settings()
    storage_uri = settings.redis_url or "memory://"
    # ``headers_enabled`` is intentionally off: our endpoints return Pydantic
    # models (not Response objects), so SlowAPI cannot inject rate-limit headers
    # into them. The Retry-After header is added by the 429 exception handler.
    return Limiter(
        key_func=client_identifier,
        storage_uri=storage_uri,
        headers_enabled=False,
        strategy="fixed-window",
    )


# Module-level singleton shared by the app and route decorators.
limiter: Limiter = build_limiter()
