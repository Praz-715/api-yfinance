"""JWT issuance and verification (HS256 via ``python-jose``).

Two token types are issued:

* **access** — short-lived (default 15 min), carries the granted ``scopes`` and
  is presented as a ``Bearer`` token to protected endpoints.
* **refresh** — longer-lived (default 24 h), single-purpose token used only to
  obtain a new access token.

Every token carries ``iss``/``aud``/``iat``/``exp``/``jti``/``type`` and is fully
validated (signature, expiry, issuer, audience, type) on the way in.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, Literal

from jose import JWTError, jwt

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.utils.timeutils import now_utc, to_epoch_seconds

TokenType = Literal["access", "refresh"]

# Scopes that may be embedded in a token. Heavy analysis endpoints require the
# ``analysis`` scope; read endpoints require ``read``.
GRANTABLE_SCOPES: frozenset[str] = frozenset({"read", "analysis"})


def _build_claims(
    *,
    subject: str,
    token_type: TokenType,
    ttl_seconds: int,
    settings: Settings,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    issued = now_utc()
    claims: dict[str, Any] = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": to_epoch_seconds(issued),
        "exp": to_epoch_seconds(issued + timedelta(seconds=ttl_seconds)),
        "jti": secrets.token_urlsafe(16),
        "type": token_type,
    }
    if scopes is not None:
        claims["scopes"] = scopes
    return claims


def sanitize_scopes(requested: list[str]) -> list[str]:
    """Intersect requested scopes with the grantable set, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for scope in requested:
        if scope in GRANTABLE_SCOPES and scope not in seen:
            seen.add(scope)
            result.append(scope)
    return result or ["read"]


def create_access_token(subject: str, scopes: list[str], settings: Settings) -> str:
    claims = _build_claims(
        subject=subject,
        token_type="access",
        ttl_seconds=settings.access_token_ttl_seconds,
        settings=settings,
        scopes=scopes,
    )
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str, scopes: list[str], settings: Settings) -> str:
    claims = _build_claims(
        subject=subject,
        token_type="refresh",
        ttl_seconds=settings.refresh_token_ttl_seconds,
        settings=settings,
        scopes=scopes,
    )
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType, settings: Settings) -> dict[str, Any]:
    """Decode and fully validate a token, enforcing the expected ``type``.

    Raises :class:`AuthenticationError` (never leaks library internals) on any
    signature, expiry, audience, issuer, or type mismatch.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except JWTError as exc:  # expired, bad signature, wrong aud/iss, malformed
        raise AuthenticationError("The provided token is invalid or has expired.") from exc

    if claims.get("type") != expected_type:
        raise AuthenticationError("The provided token is not valid for this operation.")

    return claims
