"""Centralised exception handlers producing the uniform error envelope.

Every handler returns ``{"error": {code, message, request_id, details}}`` and
*never* leaks internals (stack traces, file paths, upstream payloads, secrets).
Unexpected exceptions are logged in full server-side but surfaced to clients as a
generic 500.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.core.exceptions import AppError
from app.core.logging import get_logger, log_security_event, request_id_ctx

logger = get_logger("errors")


def _envelope(code: str, message: str, status: int, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id_ctx.get(),
                "details": details or {},
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.error_code, exc.message, exc.status_code, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Surface only safe field/location information, never raw input values.
        fields = [
            {"location": list(err.get("loc", [])), "message": err.get("msg", "invalid")}
            for err in exc.errors()
        ]
        return _envelope(
            "validation_error",
            "One or more request parameters were invalid.",
            422,
            {"fields": fields},
        )

    @app.exception_handler(RateLimitExceeded)
    async def _handle_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        log_security_event("rate_limit_exceeded", path=request.url.path, limit=str(exc.limit))
        response = _envelope(
            "rate_limited",
            "Too many requests. Please slow down and retry later.",
            429,
        )
        # Preserve standard Retry-After/limit headers when available.
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            response.headers["Retry-After"] = str(retry_after)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            400: "bad_request",
            401: "authentication_failed",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
        }.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be processed."
        return _envelope(code, message, exc.status_code)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Full detail to the server log; opaque generic message to the client.
        logger.error(
            "unhandled_exception",
            exc_info=exc,
            extra={"path": request.url.path, "method": request.method},
        )
        return _envelope("internal_error", "An unexpected error occurred.", 500)
