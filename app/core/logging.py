"""Structured (JSON) logging.

Every log record is emitted as a single-line JSON document so that Vercel's log
drains (and any downstream log aggregator) can parse them without regexes. A
request-id is propagated through a :class:`~contextvars.ContextVar` so that all
logs produced while handling a request can be correlated.

A dedicated ``security`` logger is provided for audit-grade security events
(invalid origins, auth failures, rate-limit violations, suspected bots).
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Correlation id for the in-flight request; "-" when outside a request scope.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_CONFIGURED = False

# Attributes present on every ``logging.LogRecord``; anything outside this set is
# treated as a structured "extra" field and merged into the JSON payload.
_RESERVED_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "request_id",
    }
)


class _RequestIdFilter(logging.Filter):
    """Inject the current request id into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """Render log records as compact JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }

        # Merge structured extras passed via ``logger.info(msg, extra={...})``.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            # Include the exception type/message but never the full traceback in
            # structured fields meant for ingestion; the traceback is appended as
            # text only when explicitly requested.
            exc_type, exc_value, _ = record.exc_info
            payload["error_type"] = getattr(exc_type, "__name__", str(exc_type))
            payload["error_message"] = str(exc_value)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging exactly once with the JSON formatter."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quieten chatty third-party loggers; their important events still surface
    # via our own structured logs.
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced application logger."""
    return logging.getLogger(f"app.{name}")


# Audit logger for security-relevant events. Kept separate so it can be routed
# to a dedicated sink/alerting pipeline in production.
security_logger = logging.getLogger("security")


def log_security_event(event: str, **fields: Any) -> None:
    """Emit a structured security audit event."""
    security_logger.warning(event, extra={"security_event": event, **fields})
