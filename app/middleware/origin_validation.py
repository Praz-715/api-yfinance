"""Strict origin/referer validation middleware.

Enforces that API (data) requests originate from an explicitly allow-listed
origin. This is defence-in-depth layered on top of CORS: CORS instructs
*browsers* not to expose responses to disallowed origins, while this middleware
actively *rejects* the request server-side.

Rejection criteria (for paths under the API prefix):

* ``Origin: null`` — rejected (sandboxed iframe / opaque origin).
* An ``Origin`` not in the allow-list — rejected (covers localhost, raw-IP, and
  arbitrary third-party domains in production).
* No ``Origin`` and no ``Referer`` — rejected in production; permitted outside
  production so CLI tools and tests work.

Pre-flight ``OPTIONS`` requests are delegated to the CORS middleware.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.logging import get_logger, log_security_event, request_id_ctx

logger = get_logger("origin")


def _origin_of(url: str) -> str | None:
    """Return the scheme://host[:port] origin of a URL, or ``None`` if unparsable."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    netloc = parts.hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme}://{netloc}".rstrip("/")


def _is_ip_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class OriginValidationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings
        self._allowed = frozenset(settings.effective_allowed_origins)

    def _reject(self, reason: str, *, origin: str | None, path: str) -> Response:
        log_security_event("origin_rejected", reason=reason, origin=origin, path=path)
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "origin_not_allowed",
                    "message": "Requests from this origin are not permitted.",
                    "request_id": request_id_ctx.get(),
                    "details": {},
                }
            },
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Only guard the data API; health/docs/root are intentionally open.
        if request.method == "OPTIONS" or not path.startswith(self._settings.api_v1_prefix):
            return await call_next(request)

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        if origin is not None:
            if origin == "null":
                return self._reject("null_origin", origin=origin, path=path)
            normalized = origin.rstrip("/")
            host = urlsplit(normalized).hostname
            if _is_ip_host(host):
                return self._reject("ip_origin", origin=origin, path=path)
            if normalized not in self._allowed:
                return self._reject("origin_not_allowed", origin=origin, path=path)
            return await call_next(request)

        if referer is not None:
            ref_origin = _origin_of(referer)
            if ref_origin is None or ref_origin not in self._allowed:
                return self._reject("referer_not_allowed", origin=referer, path=path)
            return await call_next(request)

        # No Origin and no Referer: only acceptable outside production.
        if self._settings.is_production:
            return self._reject("missing_origin", origin=None, path=path)
        return await call_next(request)
