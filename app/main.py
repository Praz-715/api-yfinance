"""FastAPI application factory.

Wires together configuration, structured logging, the security middleware stack,
CORS, rate limiting, exception handling, dependency singletons, and routers.
Exposes a module-level ``app`` for ASGI servers (Uvicorn locally, Vercel's Python
runtime in production).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app import __version__
from app.core.cache import build_cache
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.error_handlers import register_exception_handlers
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.bot_protection import BotProtectionMiddleware
from app.middleware.origin_validation import OriginValidationMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import analysis, auth, health, market, stock
from app.security.rate_limit import limiter
from app.services.market_data import MarketDataService
from app.services.providers.manager import ProviderManager
from app.services.universe import MarketScreener

logger = get_logger("main")


def _init_singletons(app: FastAPI, settings: Settings) -> None:
    """Construct application-scoped singletons and attach them to ``app.state``.

    Performed eagerly at construction time (not only in ``lifespan``) so the
    application is fully functional even on serverless runtimes that do not
    execute ASGI lifespan events. The HTTP client is created lazily on first use.
    """
    cache = build_cache(settings)
    providers = ProviderManager(settings)
    market_data = MarketDataService(providers, cache, settings)
    screener = MarketScreener(market_data, cache, settings)

    app.state.cache = cache
    app.state.providers = providers
    app.state.market_data = market_data
    app.state.screener = screener


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up the shared HTTP client and guarantee graceful teardown."""
    settings: Settings = get_settings()
    await app.state.providers.startup()
    logger.info(
        "application_started",
        extra={"environment": settings.environment, "version": __version__},
    )
    try:
        yield
    finally:
        await app.state.providers.shutdown()
        await app.state.cache.close()
        logger.info("application_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    # Interactive docs are exposed only outside production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.project_name,
        version=__version__,
        description=(
            "Production-grade realtime and historical analysis API for Indonesian "
            "(IDX) equities.\n\n"
            "All `/api/v1` data endpoints require authentication (`X-API-Key` header "
            "or `Authorization: Bearer <jwt>`) **and** an allow-listed browser "
            "origin. Responses use a uniform `{meta, data}` envelope; errors use a "
            "uniform `{error}` envelope."
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        contact={"name": "teguh-prasetyo.com", "url": "https://www.teguh-prasetyo.com"},
        license_info={"name": "Proprietary"},
        servers=[
            {"url": "https://api.teguh-prasetyo.com", "description": "Production"},
            {"url": "http://localhost:8000", "description": "Local development"},
        ],
        openapi_tags=[
            {"name": "system", "description": "Health and service metadata."},
            {"name": "auth", "description": "JWT token issuance and refresh."},
            {"name": "stock", "description": "Realtime quotes for IDX symbols."},
            {"name": "history", "description": "Paginated historical OHLCV."},
            {"name": "analysis", "description": "Technical indicators and composite signals."},
            {"name": "market", "description": "Market-wide screeners over the IDX universe."},
        ],
    )

    # SlowAPI integration: expose the limiter for the per-route decorators.
    app.state.limiter = limiter

    _init_singletons(app, settings)
    register_exception_handlers(app)

    # ---------------------------------------------------------------- middleware
    # Order matters: with ``add_middleware`` the *last* added runs *outermost*.
    # Effective request order (outer → inner):
    #   RequestContext → SecurityHeaders → CORS → BotProtection → OriginValidation → BodyLimit
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(OriginValidationMiddleware, settings=settings)
    app.add_middleware(BotProtectionMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.effective_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, enable_docs_csp=docs_enabled)
    app.add_middleware(RequestContextMiddleware, timeout_seconds=settings.request_timeout_seconds)

    # ------------------------------------------------------------------- routers
    prefix = settings.api_v1_prefix
    app.include_router(health.router)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(stock.router, prefix=prefix)
    app.include_router(stock.history_router, prefix=prefix)
    app.include_router(analysis.router, prefix=prefix)
    app.include_router(market.router, prefix=prefix)
    app.include_router(market.movers_router, prefix=prefix)

    @app.get("/", tags=["system"], summary="API root")
    async def root() -> dict[str, str]:
        return {
            "name": settings.project_name,
            "version": __version__,
            "status": "operational",
            "documentation": "/docs" if docs_enabled else "disabled",
        }

    return app


app = create_app()
