"""Request body size-limit middleware.

Rejects oversized requests early by inspecting the declared ``Content-Length``.
On Vercel (and from any well-behaved client) ``Content-Length`` is always present
for requests carrying a body, so this reliably bounds memory usage and provides a
basic DoS mitigation without consuming the request stream (which would interfere
with downstream body parsing under Starlette's ``BaseHTTPMiddleware``).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_logger, log_security_event, request_id_ctx

logger = get_logger("body_limit")

# Methods that may legitimately carry a request body.
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    def _too_large(self, path: str) -> Response:
        log_security_event("payload_too_large", path=path, limit=self._max_bytes)
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "payload_too_large",
                    "message": "The request payload exceeds the permitted size.",
                    "request_id": request_id_ctx.get(),
                    "details": {"max_bytes": self._max_bytes},
                }
            },
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _BODY_METHODS:
            declared = request.headers.get("content-length")
            if declared is not None:
                try:
                    if int(declared) > self._max_bytes:
                        return self._too_large(request.url.path)
                except ValueError:
                    # A malformed Content-Length is itself a reason to reject.
                    return self._too_large(request.url.path)

        return await call_next(request)
