"""Vercel serverless entry point.

Vercel's Python runtime discovers the ASGI application exported as ``app`` in
this module and serves it for every route rewritten to ``/api/index`` (see
``vercel.json``). All application wiring lives in :mod:`app.main`.
"""

from __future__ import annotations

from app.main import app

__all__ = ["app"]
