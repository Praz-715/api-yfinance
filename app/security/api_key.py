"""API-key verification using constant-time comparison.

Supports key rotation: multiple keys may be valid simultaneously (configure the
new and previous key, deploy, then retire the old key). Comparison is performed
against every configured key with :func:`hmac.compare_digest` to avoid leaking
information through timing side-channels.
"""

from __future__ import annotations

import hmac

from app.core.config import Settings


def verify_api_key(presented: str | None, settings: Settings) -> bool:
    """Return ``True`` iff ``presented`` matches a configured key.

    The comparison is constant-time and always iterates over the full key set so
    that the work performed is independent of which key (if any) matched.
    """
    if not presented:
        return False

    presented_bytes = presented.encode("utf-8")
    matched = False
    for key in settings.api_keys:
        if hmac.compare_digest(presented_bytes, key.encode("utf-8")):
            matched = True
    return matched
