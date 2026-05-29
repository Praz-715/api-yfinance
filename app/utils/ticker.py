"""Indonesian (IDX) ticker validation and normalisation.

IDX equity symbols are four uppercase letters (e.g. ``BBCA``, ``TLKM``). On the
data providers used here they are suffixed with the Jakarta exchange code
``.JK`` (e.g. ``BBCA.JK``). This module is the single, strict gate for any
user-supplied symbol — defence against injection, oversized input, and
provider-side surprises.
"""

from __future__ import annotations

import re

from app.core.exceptions import InvalidTickerError

# IDX exchange suffix used by the upstream providers.
IDX_SUFFIX = ".JK"

# Base symbol: 1–6 ASCII letters/digits, must start with a letter. IDX tickers
# are 4 letters, but the range is kept slightly wider to tolerate rights/warrant
# symbols (e.g. ``BBCA-R``) without ever accepting free-form text.
_BASE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}(-[A-Z0-9]{1,2})?$")
_FULL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}(-[A-Z0-9]{1,2})?\.JK$")

MAX_SYMBOL_LENGTH = 12


def normalize_symbol(raw: str) -> str:
    """Validate ``raw`` and return the canonical ``<BASE>.JK`` symbol.

    Raises :class:`InvalidTickerError` for anything that is not unambiguously a
    well-formed IDX symbol. The check is allow-list based: only characters that
    can appear in a real symbol are permitted.
    """
    if not isinstance(raw, str):
        raise InvalidTickerError()

    candidate = raw.strip().upper()
    if not candidate or len(candidate) > MAX_SYMBOL_LENGTH:
        raise InvalidTickerError()

    if candidate.endswith(IDX_SUFFIX):
        if not _FULL_RE.match(candidate):
            raise InvalidTickerError()
        return candidate

    if not _BASE_RE.match(candidate):
        raise InvalidTickerError()
    return f"{candidate}{IDX_SUFFIX}"


def base_symbol(normalized: str) -> str:
    """Return the bare IDX symbol (``BBCA``) from a normalised one (``BBCA.JK``)."""
    return normalized[: -len(IDX_SUFFIX)] if normalized.endswith(IDX_SUFFIX) else normalized
