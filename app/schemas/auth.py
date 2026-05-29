"""Schemas for the JWT authentication flow."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TokenRequest(BaseModel):
    """Request body to mint tokens. Authentication itself is via the API key
    header; this body only narrows the requested scopes."""

    model_config = ConfigDict(extra="forbid")

    scopes: list[str] = Field(
        default_factory=lambda: ["read", "analysis"],
        description="Subset of grantable scopes to embed in the access token.",
        max_length=16,
    )


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=16, max_length=4096)


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds.")
    scopes: list[str]
