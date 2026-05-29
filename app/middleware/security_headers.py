"""Security response-header middleware.

Applies a strict set of hardening headers to every response. API (JSON)
responses receive a maximally locked-down Content-Security-Policy
(``default-src 'none'``). The interactive docs (enabled only outside production)
receive a narrowly relaxed CSP permitting the Swagger UI assets.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# CSP for pure JSON API responses: deny everything; forbid framing entirely.
_API_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

# CSP for the Swagger UI / ReDoc pages (development only). Limits script/style/
# image sources to the jsDelivr CDN that FastAPI uses for its docs assets.
_DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' https://fastapi.tiangolo.com data:; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)

_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, enable_docs_csp: bool) -> None:
        super().__init__(app)
        self._enable_docs_csp = enable_docs_csp

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        is_docs = self._enable_docs_csp and request.url.path in _DOCS_PATHS
        response.headers["Content-Security-Policy"] = _DOCS_CSP if is_docs else _API_CSP

        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = _PERMISSIONS_POLICY
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        # Avoid advertising the server implementation.
        response.headers["Server"] = "secure-api"
        return response
