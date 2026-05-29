"""FastAPI security dependencies: authentication and scope authorization.

A request is authenticated by *either*:

* a valid ``X-API-Key`` header (machine-to-machine, full scopes), or
* a valid ``Authorization: Bearer <jwt>`` access token (scoped).

Outside production, when no API keys are configured, an anonymous development
principal is granted so the API is usable for local development and tests. This
path is structurally impossible in production because configuration validation
requires at least one API key there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.logging import log_security_event
from app.security.api_key import verify_api_key
from app.security.jwt import GRANTABLE_SCOPES, decode_token

_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller and its granted scopes."""

    subject: str
    method: str  # "api_key" | "jwt" | "dev"
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


async def authenticate(
    request: Request,
    api_key: str | None = Depends(_api_key_scheme),
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Resolve and return the :class:`Principal` for the request, or raise 401."""
    # 1) API key — full trust, all grantable scopes.
    if api_key is not None:
        if verify_api_key(api_key, settings):
            return Principal(subject="api-key", method="api_key", scopes=frozenset(GRANTABLE_SCOPES))
        log_security_event(
            "auth_invalid_api_key",
            path=request.url.path,
            client=request.client.host if request.client else None,
        )
        raise AuthenticationError("The supplied API key is invalid.")

    # 2) Bearer JWT access token — scoped trust.
    if bearer is not None and bearer.credentials:
        claims = decode_token(bearer.credentials, expected_type="access", settings=settings)
        scopes = frozenset(claims.get("scopes", [])) & GRANTABLE_SCOPES
        return Principal(subject=str(claims.get("sub", "token")), method="jwt", scopes=scopes)

    # 3) Development convenience (never reachable in production).
    if not settings.is_production and not settings.api_keys:
        return Principal(subject="dev", method="dev", scopes=frozenset(GRANTABLE_SCOPES))

    log_security_event(
        "auth_missing_credentials",
        path=request.url.path,
        client=request.client.host if request.client else None,
    )
    raise AuthenticationError("Authentication credentials are required.")


def require_scope(scope: str):
    """Return a dependency that asserts the principal holds ``scope``."""

    async def _dependency(principal: Principal = Depends(authenticate)) -> Principal:
        if not principal.has_scope(scope):
            log_security_event(
                "authz_insufficient_scope",
                subject=principal.subject,
                required_scope=scope,
            )
            raise AuthorizationError("The token does not grant the required scope.")
        return principal

    return _dependency


# Convenience dependencies for the two scope tiers.
require_read = require_scope("read")
require_analysis = require_scope("analysis")
