"""Application exception hierarchy and error contracts.

Every error surfaced to a client is mapped to a stable, machine-readable
``error_code`` and a *safe* human message. Internal details (stack traces,
upstream payloads, file paths, secrets) are logged but never returned.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected, client-safe application errors."""

    status_code: int = 500
    error_code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.error_code = error_code or self.error_code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(AppError):
    status_code = 422
    error_code = "validation_error"
    message = "The request contained invalid parameters."


class InvalidTickerError(ValidationError):
    error_code = "invalid_ticker"
    message = "The supplied ticker symbol is not a valid Indonesian equity symbol."


class AuthenticationError(AppError):
    status_code = 401
    error_code = "authentication_failed"
    message = "Authentication credentials were missing or invalid."


class AuthorizationError(AppError):
    status_code = 403
    error_code = "forbidden"
    message = "You are not permitted to access this resource."


class OriginNotAllowedError(AuthorizationError):
    error_code = "origin_not_allowed"
    message = "Requests from this origin are not permitted."


class RateLimitError(AppError):
    status_code = 429
    error_code = "rate_limited"
    message = "Too many requests. Please slow down."


class PayloadTooLargeError(AppError):
    status_code = 413
    error_code = "payload_too_large"
    message = "The request payload exceeds the permitted size."


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"
    message = "The requested resource was not found."


class UpstreamError(AppError):
    """Raised when an upstream market-data provider fails or is unavailable."""

    status_code = 502
    error_code = "upstream_error"
    message = "The market-data provider is currently unavailable."


class UpstreamTimeoutError(UpstreamError):
    status_code = 504
    error_code = "upstream_timeout"
    message = "The market-data provider did not respond in time."


class InsufficientDataError(AppError):
    status_code = 422
    error_code = "insufficient_data"
    message = "Not enough data is available to compute the requested analysis."
