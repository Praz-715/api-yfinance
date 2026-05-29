"""Provider manager: shared HTTP client, ordered failover, and lifecycle.

Owns the singleton :class:`httpx.AsyncClient` (connection pooling + HTTP/2) and
an ordered list of providers. ``get_chart`` tries each provider in priority order
and returns the first successful result, transparently failing over on upstream
errors. Additional providers can be registered without touching callers — they
only need to implement :class:`MarketDataProvider`.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.exceptions import UpstreamError, UpstreamTimeoutError
from app.core.logging import get_logger
from app.services.providers.base import ChartResult, MarketDataProvider
from app.services.providers.yahoo import YahooFinanceProvider

logger = get_logger("provider.manager")


class ProviderManager:
    """Coordinates one or more market-data providers behind a shared client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Priority-ordered providers. Yahoo is primary (and itself fails over
        # across two hosts). The list is the single extension point for adding
        # IDX-native or alternative fallback providers.
        self._providers: list[MarketDataProvider] = [YahooFinanceProvider(settings)]
        self._client: httpx.AsyncClient | None = None

    @property
    def primary_source(self) -> str:
        return self._providers[0].name

    async def startup(self) -> None:
        """Create the shared HTTP client (called on application startup)."""
        if self._client is None:
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
            self._client = httpx.AsyncClient(
                http2=False,
                limits=limits,
                timeout=httpx.Timeout(self._settings.provider_timeout_seconds),
                follow_redirects=True,
            )
            logger.info("provider_client_started")

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("provider_client_closed")

    def _ensure_client(self) -> httpx.AsyncClient:
        # Lazily construct the client if startup() did not run (defensive for
        # serverless cold paths). Reused across the warm instance.
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.provider_timeout_seconds),
                follow_redirects=True,
            )
        return self._client

    async def get_chart(
        self,
        symbol: str,
        *,
        range_: str | None = None,
        interval: str = "1d",
        period1: int | None = None,
        period2: int | None = None,
    ) -> ChartResult:
        """Return the first successful chart across the provider chain."""
        client = self._ensure_client()
        last_error: Exception | None = None

        for provider in self._providers:
            try:
                return await provider.fetch_chart(
                    client,
                    symbol,
                    range_=range_,
                    interval=interval,
                    period1=period1,
                    period2=period2,
                )
            except (UpstreamError, UpstreamTimeoutError) as exc:
                last_error = exc
                logger.warning(
                    "provider_failover",
                    extra={"provider": provider.name, "symbol": symbol, "error": str(exc)},
                )

        if isinstance(last_error, UpstreamTimeoutError):
            raise last_error
        raise UpstreamError("All market-data providers are unavailable.") from last_error
