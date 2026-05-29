"""Vercel serverless entry point.

Vercel's Python runtime (``@vercel/python``) builds this module and serves the
ASGI application exported as ``app`` for every request (``vercel.json`` routes
``/(.*)`` here). All application wiring lives in :mod:`app.main`.
"""

from __future__ import annotations

from app.main import app

__all__ = ["app"]
