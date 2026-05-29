# API Documentation

This folder contains the generated API reference.

| File | Purpose |
|---|---|
| [`openapi.json`](openapi.json) | The OpenAPI 3.1 specification, generated from the live FastAPI app. |
| [`index.html`](index.html) | Standalone Redoc reference that renders `openapi.json`. |

## Regenerate the spec

The spec is produced directly from the application, so it never drifts from the
code. After changing routes, parameters, or response models, regenerate it:

```bash
python scripts/export_openapi.py
```

## View the reference

The interactive docs are available three ways:

1. **Live (development only):** run the API and open
   `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc`.
   These endpoints are **disabled in production** for security.

2. **Static Redoc page (any environment):** serve this folder over HTTP and open
   `index.html` (a local file open won't work — browsers block `fetch` of
   `openapi.json` from `file://`):

   ```bash
   python -m http.server 8080 --directory docs
   # then open http://localhost:8080/
   ```

3. **Import `openapi.json`** into Postman, Insomnia, Stoplight, or generate
   client SDKs with `openapi-generator`.

## Authentication in the reference

Every `/api/v1` data endpoint declares two accepted security schemes:

- `APIKeyHeader` → send `X-API-Key: <your key>`
- `HTTPBearer` → send `Authorization: Bearer <access token>`

Obtain a bearer token from `POST /api/v1/auth/token` (authenticated with your API
key). Remember that, in production, requests must also carry an allow-listed
`Origin` header.
