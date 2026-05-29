# Indonesian Stock Analysis API

A production-grade, security-hardened, async-first API for **realtime and
historical analysis of Indonesian (IDX) equities**, built with **FastAPI** and
optimised for **Vercel serverless** deployment.

It exposes quotes, historical OHLCV, a full technical-indicator suite, composite
trading signals (with confidence and risk classification), and market-wide
screeners over a curated IDX universe — all behind an enterprise-grade security
perimeter that restricts access to the official web origin.

---

## Table of contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Quick start (local)](#quick-start-local)
4. [Environment variables](#environment-variables)
5. [Authentication](#authentication)
6. [Endpoints](#endpoints)
7. [Response format](#response-format)
8. [Security model](#security-model)
9. [Data providers](#data-providers)
10. [Deployment to Vercel](#deployment-to-vercel)
11. [Testing](#testing)
12. [Disclaimer](#disclaimer)

---

## Features

- **Realtime quotes** for IDX symbols (`BBCA`, `TLKM`, …).
- **Historical OHLCV** with date-range, interval, pagination, and row caps.
- **Technical indicators**: SMA/EMA, RSI(14), MACD, Bollinger Bands, ATR(14),
  annualised volatility, floor-trader pivot support/resistance, regression-based
  trend detection, and volume-spike detection.
- **Composite trading signal** combining five weighted factors into a discrete
  signal with a `confidence` score and a volatility-derived `risk_level`.
- **Market screeners**: summary, top gainers, top losers, unusual volume.
- **Async everywhere** with connection pooling, retries, circuit breakers, and
  provider failover.
- **Redis-compatible cache** abstraction (in-memory fallback).
- **Structured JSON logging** with per-request correlation ids and a dedicated
  security audit logger.

## Architecture

```
api/
  index.py                # Vercel entry point — exposes the ASGI `app`
app/
  main.py                 # App factory: middleware, CORS, routers, lifespan
  dependencies.py         # App-scoped DI providers
  error_handlers.py       # Uniform, leak-proof error envelopes
  core/
    config.py             # Env-driven settings; fail-closed in production
    logging.py            # JSON logging + security audit logger
    cache.py              # CacheBackend (Redis / in-memory)
    circuit_breaker.py    # Async circuit breaker
    exceptions.py         # Client-safe exception hierarchy
  security/
    api_key.py            # Constant-time API-key verification
    jwt.py                # Access/refresh token issuance & validation
    rate_limit.py         # SlowAPI limiter (per-client IP)
    dependencies.py       # Auth + scope dependencies
  middleware/
    request_context.py    # Request id + hard timeout
    security_headers.py   # CSP/HSTS/XFO/… hardening headers
    origin_validation.py  # Strict origin/referer allow-listing
    body_limit.py         # Payload size cap
    bot_protection.py     # UA blocklist + suspicious-pattern detection
  services/
    providers/            # Pluggable market-data providers (Yahoo + failover)
    market_data.py        # Quotes / history + caching
    indicators.py         # Pure pandas/numpy indicator maths
    analysis.py           # Indicator bundle + signal engine
    universe.py           # IDX universe + screeners
  routers/                # stock, history, analysis, market, auth, health
  schemas/                # Pydantic v2 request/response contracts
  utils/                  # Ticker validation, time helpers
tests/                    # pytest suite (security, CORS, rate-limit, …)
```

## Quick start (local)

Requires **Python 3.12**.

```bash
# 1. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements-dev.txt

# 2. Configure the environment
copy .env.example .env            # Windows  (cp on macOS/Linux)
#   For local dev you may leave API_KEYS empty — see "Authentication".

# 3. Run the development server
uvicorn app.main:app --reload --port 8000
```

Then open:

- Interactive docs (non-production only): http://localhost:8000/docs
- Health probe: http://localhost:8000/health

> In **development** the API is intentionally usable for testing: requests with
> no `Origin`/`Referer` are allowed, `localhost` origins are permitted, and if
> `API_KEYS` is empty an anonymous development principal is granted. **None of
> these relaxations apply in production** — see [Security model](#security-model).

## Environment variables

See [`.env.example`](.env.example) for the full annotated list. The essentials:

| Variable | Required | Description |
|---|---|---|
| `ENVIRONMENT` | yes | `development` \| `staging` \| `production`. |
| `API_KEYS` | **prod** | Comma-separated API keys (rotation-ready). |
| `JWT_SECRET` | **prod** | ≥ 32-char signing secret. |
| `ALLOWED_ORIGINS` | **prod** | Comma-separated browser origins allowed to call the API. |
| `REDIS_URL` | no | Redis/KV URL; falls back to in-memory cache when unset. |
| `RATE_LIMIT_PUBLIC` | no | Default `60/minute`. |
| `RATE_LIMIT_HEAVY` | no | Default `10/minute` (analysis & screeners). |

Generate secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # API key
python -c "import secrets; print(secrets.token_hex(32))"       # JWT secret
```

In **production** the app **refuses to start** if `API_KEYS` is empty, `JWT_SECRET`
is shorter than 32 characters, or `ALLOWED_ORIGINS` is unset (fail-closed).

## Authentication

Two interchangeable credentials are accepted on every `/api/v1` data endpoint:

1. **API key** — header `X-API-Key: <key>` (machine-to-machine; full scopes).
2. **JWT access token** — header `Authorization: Bearer <token>` (scoped).

Mint tokens with your API key:

```bash
curl -X POST https://api.example.com/api/v1/auth/token \
  -H "X-API-Key: $API_KEY" \
  -H "Origin: https://teguh-prasetyo.com" \
  -H "Content-Type: application/json" \
  -d '{"scopes": ["read", "analysis"]}'
```

Response contains `access_token` (short-lived) and `refresh_token`. Exchange the
refresh token at `POST /api/v1/auth/refresh`.

Scopes:

- `read` — quotes & history.
- `analysis` — technical indicators, signals, and market screeners (heavy).

## Endpoints

All data endpoints are prefixed with `/api/v1` and require authentication and an
allow-listed origin.

| Method | Path | Scope | Rate limit | Description |
|---|---|---|---|---|
| `GET` | `/stock/{symbol}` | `read` | public | Realtime quote. |
| `GET` | `/history/{symbol}` | `read` | public | Historical OHLCV (paginated). |
| `GET` | `/technical/{symbol}` | `analysis` | heavy | Full indicator bundle. |
| `GET` | `/signal/{symbol}` | `analysis` | heavy | Composite trading signal. |
| `GET` | `/market/summary` | `analysis` | heavy | Universe-wide snapshot. |
| `GET` | `/top-gainers` | `analysis` | heavy | Top gainers by % change. |
| `GET` | `/top-losers` | `analysis` | heavy | Top losers by % change. |
| `GET` | `/unusual-volume` | `analysis` | heavy | High relative-volume names. |
| `POST` | `/auth/token` | — | auth | Issue access/refresh tokens. |
| `POST` | `/auth/refresh` | — | auth | Exchange a refresh token. |
| `GET` | `/health` | — | — | Liveness probe (open). |

Query parameters:

- `history`: `start` (date), `end` (date), `interval` (`1m`…`1mo`), `page`, `page_size`.
- `technical` / `signal`: `interval`.
- screeners: `limit`.

Example:

```bash
curl "https://api.example.com/api/v1/signal/BBCA?interval=1d" \
  -H "X-API-Key: $API_KEY" \
  -H "Origin: https://teguh-prasetyo.com"
```

## Response format

Every successful response uses a uniform envelope:

```json
{
  "meta": {
    "symbol": "BBCA.JK",
    "exchange": "Jakarta",
    "currency": "IDR",
    "timezone": "Asia/Jakarta",
    "source": "yahoo_finance",
    "generated_at": "2026-05-29T08:00:00+00:00",
    "cached": false,
    "disclaimer": "Data is provided for informational purposes only ..."
  },
  "data": { "...": "endpoint-specific payload" }
}
```

Errors use a uniform, leak-proof envelope:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Too many requests. Please slow down and retry later.",
    "request_id": "a1b2c3d4e5f6a7b8",
    "details": {}
  }
}
```

## API reference (OpenAPI)

A complete OpenAPI 3.1 specification is generated from the live application and
committed under [`docs/`](docs/):

- [`docs/openapi.json`](docs/openapi.json) — the specification.
- [`docs/index.html`](docs/index.html) — a standalone Redoc reference.

Regenerate after any route/schema change:

```bash
python scripts/export_openapi.py
```

View it:

```bash
# Live (development only):
uvicorn app.main:app --reload --port 8000   # → http://localhost:8000/docs

# Static Redoc page (any environment):
python -m http.server 8080 --directory docs  # → http://localhost:8080/
```

See [`docs/README.md`](docs/README.md) for details. (The live `/docs`,
`/redoc`, and `/openapi.json` endpoints are disabled in production.)

## Security model

| Control | Implementation |
|---|---|
| **Strict CORS** | Explicit origin allow-list; **no wildcard**; credentials enabled. |
| **Origin validation** | Server-side rejection of disallowed/`null`/IP/localhost origins (defence-in-depth beyond CORS). |
| **API-key auth** | Constant-time (`hmac.compare_digest`) comparison; rotation-ready. |
| **JWT auth** | HS256 access/refresh tokens; full `iss`/`aud`/`exp`/`type` validation; scoped. |
| **Rate limiting** | Per-client-IP (X-Forwarded-For aware); `60/min` public, `10/min` heavy. |
| **Bot protection** | User-Agent blocklist, request fingerprinting, suspicious-pattern detection. |
| **Security headers** | CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP/CORP. |
| **DoS mitigation** | Body-size cap, hard request timeout, bounded upstream concurrency, caching. |
| **Input validation** | Strict allow-list ticker regex; Pydantic v2 models; oversized-payload rejection. |
| **Error handling** | No stack traces, paths, secrets, or dependency info leaked to clients. |
| **Audit logging** | Dedicated `security` logger for origin rejections, auth failures, rate-limit violations, bot blocks. |
| **Fail-closed config** | Production refuses to boot without strong secrets and configured origins. |

Production additionally **disables the interactive docs** (`/docs`, `/redoc`,
`/openapi.json`) to avoid exposing the schema surface.

## Data providers

A modular provider architecture (`app/services/providers`) exposes a single
`MarketDataProvider` interface. The shipped **Yahoo Finance** provider:

- uses the public `/v8/finance/chart` endpoint (no crumb required);
- fails over across two Yahoo hosts (`query1`/`query2`), each guarded by its own
  **circuit breaker**;
- retries transient `5xx`/`429` responses with backoff;
- enforces per-request timeouts.

The `ProviderManager` adds **provider-level failover** and owns the shared,
pooled `httpx.AsyncClient`. Additional IDX-native or fallback providers can be
added simply by implementing `MarketDataProvider` and registering them — no
changes to callers are required.

## Deployment to Vercel

1. **Push** this repository to a Git provider connected to Vercel.
2. **Project settings → General**: ensure the Python version is **3.12**.
3. **Project settings → Environment Variables**: set (at minimum)
   `ENVIRONMENT=production`, `API_KEYS`, `JWT_SECRET`, and `ALLOWED_ORIGINS`.
   Optionally set `REDIS_URL` (e.g. Vercel KV / Upstash) for cross-instance
   caching and shared rate-limit state.
4. **Deploy**. [`vercel.json`](vercel.json) routes all traffic to
   `api/index.py`, which exposes the ASGI `app` from `app.main`. The function is
   configured with 1 GB memory and a 60 s max duration.

No build step is required — Vercel installs `requirements.txt` automatically.

```bash
# Optional: deploy from the CLI
npm i -g vercel
vercel            # preview
vercel --prod     # production
```

> **Note on cold starts.** pandas/numpy add to the cold-start footprint. Memory
> is set to 1 GB to keep cold starts fast; caching (Redis or in-memory) absorbs
> repeated requests within a warm instance.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers indicator maths, input validation, CORS/origin rejection,
authentication & scope enforcement, rate limiting, and the security headers /
bot-protection / payload-limit controls. Upstream network access is replaced with
a deterministic synthetic provider so tests are fast and offline.

## Disclaimer

This API provides market data and quantitative indicators for **informational
purposes only**. Data may be delayed and is sourced from third parties. Nothing
returned by this API constitutes investment advice. Always verify with an
authoritative source before making financial decisions.
