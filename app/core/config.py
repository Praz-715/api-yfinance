"""Application configuration.

All runtime configuration is sourced from environment variables (or an optional
local ``.env`` file for development). Secrets are *never* hardcoded. The settings
object enforces fail-closed behaviour in production: if a required secret is
missing or weak, the application refuses to start.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]

# Origins implicitly trusted while running outside production so the API remains
# usable for local development, automated tests, and preview deployments.
_DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
)


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ------------------------------------------------------------------ general
    environment: Environment = Field(default="development", alias="ENVIRONMENT")
    project_name: str = Field(default="Indonesian Stock Analysis API", alias="PROJECT_NAME")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ----------------------------------------------------------------- security
    # Comma-separated list of accepted API keys (supports rotation: keep the new
    # and previous key live simultaneously, then drop the old one).
    api_keys_raw: str = Field(default="", alias="API_KEYS")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_issuer: str = Field(default="teguh-prasetyo.com", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="teguh-prasetyo.com", alias="JWT_AUDIENCE")
    access_token_ttl_seconds: int = Field(default=900, alias="ACCESS_TOKEN_TTL_SECONDS")
    refresh_token_ttl_seconds: int = Field(default=86_400, alias="REFRESH_TOKEN_TTL_SECONDS")

    # Comma-separated list of browser origins permitted to call the API.
    allowed_origins_raw: str = Field(
        default="https://teguh-prasetyo.com,https://www.teguh-prasetyo.com",
        alias="ALLOWED_ORIGINS",
    )

    # --------------------------------------------------------------- rate limit
    rate_limit_public: str = Field(default="60/minute", alias="RATE_LIMIT_PUBLIC")
    rate_limit_heavy: str = Field(default="10/minute", alias="RATE_LIMIT_HEAVY")
    rate_limit_auth: str = Field(default="20/minute", alias="RATE_LIMIT_AUTH")

    # -------------------------------------------------------------- cache/redis
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    cache_default_ttl_seconds: int = Field(default=30, alias="CACHE_DEFAULT_TTL_SECONDS")
    quote_cache_ttl_seconds: int = Field(default=15, alias="QUOTE_CACHE_TTL_SECONDS")
    history_cache_ttl_seconds: int = Field(default=300, alias="HISTORY_CACHE_TTL_SECONDS")
    market_cache_ttl_seconds: int = Field(default=60, alias="MARKET_CACHE_TTL_SECONDS")
    fundamentals_cache_ttl_seconds: int = Field(default=3600, alias="FUNDAMENTALS_CACHE_TTL_SECONDS")

    # ----------------------------------------------------------------- providers
    provider_timeout_seconds: float = Field(default=8.0, alias="PROVIDER_TIMEOUT_SECONDS")
    provider_max_retries: int = Field(default=2, alias="PROVIDER_MAX_RETRIES")
    provider_backoff_seconds: float = Field(default=0.4, alias="PROVIDER_BACKOFF_SECONDS")
    circuit_breaker_failure_threshold: int = Field(default=5, alias="CIRCUIT_BREAKER_FAILURE_THRESHOLD")
    circuit_breaker_reset_seconds: float = Field(default=30.0, alias="CIRCUIT_BREAKER_RESET_SECONDS")
    market_universe_concurrency: int = Field(default=8, alias="MARKET_UNIVERSE_CONCURRENCY")

    # -------------------------------------------------------------------- limits
    max_body_bytes: int = Field(default=16_384, alias="MAX_BODY_BYTES")
    max_history_rows: int = Field(default=5_000, alias="MAX_HISTORY_ROWS")
    request_timeout_seconds: float = Field(default=20.0, alias="REQUEST_TIMEOUT_SECONDS")

    # ------------------------------------------------------------ bot protection
    blocked_user_agents_raw: str = Field(
        default="sqlmap,nikto,nessus,masscan,zgrab,nmap,dirbuster,wpscan,acunetix,nuclei",
        alias="BLOCKED_USER_AGENTS",
    )

    # -------------------------------------------------------------- derived/props
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def api_keys(self) -> frozenset[str]:
        """The set of currently-accepted API keys."""
        return frozenset(k.strip() for k in self.api_keys_raw.split(",") if k.strip())

    @property
    def configured_origins(self) -> tuple[str, ...]:
        """Origins explicitly configured by the operator (normalised, no trailing slash)."""
        return tuple(
            o.strip().rstrip("/")
            for o in self.allowed_origins_raw.split(",")
            if o.strip()
        )

    @property
    def effective_allowed_origins(self) -> tuple[str, ...]:
        """Origins accepted by CORS/origin validation for the current environment."""
        origins = list(self.configured_origins)
        if not self.is_production:
            for dev_origin in _DEV_ORIGINS:
                if dev_origin not in origins:
                    origins.append(dev_origin)
        return tuple(origins)

    @property
    def allowed_origin_hosts(self) -> frozenset[str]:
        """Hostnames (without scheme/port) extracted from the allowed origins."""
        hosts: set[str] = set()
        for origin in self.effective_allowed_origins:
            host = urlsplit(origin).hostname
            if host:
                hosts.add(host.lower())
        return frozenset(hosts)

    @property
    def blocked_user_agents(self) -> tuple[str, ...]:
        return tuple(
            ua.strip().lower()
            for ua in self.blocked_user_agents_raw.split(",")
            if ua.strip()
        )

    # ----------------------------------------------------------- fail-closed gate
    @model_validator(mode="after")
    def _enforce_security_invariants(self) -> "Settings":
        """Guarantee that production never boots with weak or missing secrets."""
        if self.is_production:
            problems: list[str] = []
            if not self.api_keys:
                problems.append("API_KEYS must define at least one key in production")
            if len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be at least 32 characters in production")
            if not self.configured_origins:
                problems.append("ALLOWED_ORIGINS must be configured in production")
            if problems:
                raise ValueError("Insecure production configuration: " + "; ".join(problems))
        elif len(self.jwt_secret) < 32:
            # Development convenience only: derive an ephemeral, process-local secret
            # so the API runs out-of-the-box. Tokens will not survive a restart.
            object.__setattr__(self, "jwt_secret", secrets.token_hex(32))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, validated settings singleton."""
    return Settings()
