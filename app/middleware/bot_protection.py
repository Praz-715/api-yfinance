"""Bot / abuse protection middleware.

Lightweight, allow-friendly heuristics that run on API paths:

* **User-Agent validation** — reject requests whose ``User-Agent`` matches a
  known scanner/exploitation-tool blocklist; reject empty UAs in production.
* **Request fingerprinting** — derive a stable fingerprint from client IP +
  User-Agent for correlation in security logs.
* **Suspicious-pattern detection** — flag obviously malicious URL/query content
  (path traversal, SQL-injection probes) that survives upstream validation.

These run *before* the (more expensive) route handlers and complement the
rate limiter rather than replacing it.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote_plus

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.logging import get_logger, log_security_event, request_id_ctx

logger = get_logger("bot_protection")

# Obvious attack signatures in the raw path/query. Legitimate IDX endpoints only
# ever contain alphanumerics, dots, dashes, slashes, and standard query syntax.
_SUSPICIOUS_RE = re.compile(
    r"(\.\./)|(<script)|(union\s+select)|(\bor\s+1=1\b)|(;--)|(/etc/passwd)|(\bdrop\s+table\b)",
    re.IGNORECASE,
)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class BotProtectionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings
        self._blocked_uas = settings.blocked_user_agents

    def _forbidden(self, reason: str, *, path: str, fingerprint: str, user_agent: str) -> Response:
        log_security_event(
            "bot_blocked",
            reason=reason,
            path=path,
            fingerprint=fingerprint,
            user_agent=user_agent[:256],
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "forbidden",
                    "message": "This request was blocked by automated protection.",
                    "request_id": request_id_ctx.get(),
                    "details": {},
                }
            },
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not path.startswith(self._settings.api_v1_prefix):
            return await call_next(request)

        user_agent = request.headers.get("user-agent", "")
        ip = _client_ip(request)
        fingerprint = hashlib.sha256(f"{ip}|{user_agent}".encode("utf-8")).hexdigest()[:24]

        # Expose the fingerprint to handlers/logs for correlation.
        request.state.fingerprint = fingerprint

        ua_lower = user_agent.lower()
        if not user_agent and self._settings.is_production:
            return self._forbidden("missing_user_agent", path=path, fingerprint=fingerprint, user_agent=user_agent)

        if any(bad in ua_lower for bad in self._blocked_uas):
            return self._forbidden("blocked_user_agent", path=path, fingerprint=fingerprint, user_agent=user_agent)

        raw_target = f"{request.url.path}?{request.url.query}" if request.url.query else request.url.path
        # Decode percent- and plus-encoding so encoded payloads cannot bypass.
        decoded_target = unquote_plus(raw_target)
        if _SUSPICIOUS_RE.search(decoded_target):
            return self._forbidden("suspicious_pattern", path=path, fingerprint=fingerprint, user_agent=user_agent)

        return await call_next(request)
