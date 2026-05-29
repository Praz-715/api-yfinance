"""Request-context middleware.

Assigns a correlation id to every request (honouring an inbound
``X-Request-ID`` when present and well-formed), binds it to the logging context,
echoes it back on the response, and enforces a hard server-side request timeout
to bound resource usage (a basic DoS mitigation).
"""

from __future__ import annotations

import asyncio
import re
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_logger, request_id_ctx

logger = get_logger("request")

# Accept only conservative, log-safe inbound request ids.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, timeout_seconds: float) -> None:
        super().__init__(app)
        self._timeout = timeout_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        inbound = request.headers.get("x-request-id", "")
        request_id = inbound if _REQUEST_ID_RE.match(inbound) else secrets.token_hex(8)
        token = request_id_ctx.set(request_id)

        try:
            response = await asyncio.wait_for(call_next(request), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning("request_timeout", extra={"path": request.url.path})
            response = JSONResponse(
                status_code=504,
                content={
                    "error": {
                        "code": "request_timeout",
                        "message": "The request took too long to process.",
                        "request_id": request_id,
                        "details": {},
                    }
                },
            )
        finally:
            request_id_ctx.reset(token)

        response.headers["X-Request-ID"] = request_id
        return response
