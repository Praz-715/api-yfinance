"""Authentication router: mint and refresh JWT access tokens.

Token issuance is gated by a valid ``X-API-Key`` (machine-to-machine bootstrap).
The minted access token carries the (sanitised) requested scopes; the refresh
token can later be exchanged for a fresh access token without re-presenting the
API key.
"""

# `from __future__ import annotations` is intentionally omitted (see stock.py):
# FastAPI needs the request-body model annotations resolved at import time.

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError
from app.core.logging import log_security_event
from app.schemas.auth import RefreshRequest, TokenRequest, TokenResponse
from app.security.api_key import verify_api_key
from app.security.dependencies import _api_key_scheme
from app.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    sanitize_scopes,
)
from app.security.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse, summary="Issue access & refresh tokens")
@limiter.limit(get_settings().rate_limit_auth)
async def issue_token(
    request: Request,
    body: TokenRequest,
    api_key: str | None = Depends(_api_key_scheme),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    # In production an API key is mandatory; outside production with no keys
    # configured a development subject is used (see configuration validation).
    if settings.api_keys or settings.is_production:
        if not verify_api_key(api_key, settings):
            log_security_event("auth_token_invalid_api_key", path=request.url.path)
            raise AuthenticationError("A valid API key is required to issue tokens.")
        subject = "api-key"
    else:
        subject = "dev"

    scopes = sanitize_scopes(body.scopes)
    access = create_access_token(subject, scopes, settings)
    refresh = create_refresh_token(subject, scopes, settings)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
        scopes=scopes,
    )


@router.post("/refresh", response_model=TokenResponse, summary="Exchange a refresh token")
@limiter.limit(get_settings().rate_limit_auth)
async def refresh_token(
    request: Request,
    body: RefreshRequest,
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    claims = decode_token(body.refresh_token, expected_type="refresh", settings=settings)
    subject = str(claims.get("sub", "token"))
    scopes = sanitize_scopes(list(claims.get("scopes", [])))
    access = create_access_token(subject, scopes, settings)
    refresh = create_refresh_token(subject, scopes, settings)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
        scopes=scopes,
    )
