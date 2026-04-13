"""Per-column anonymization primitives.

Each function takes a Polars Series and returns a transformed Series.
Row count is preserved except for suppression (done by the k-anonymity step).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import date, datetime

import polars as pl

# --- direct-identifier primitives --------------------------------------------

def mask(series: pl.Series, keep_prefix: int = 0, keep_suffix: int = 0,
         mask_char: str = "*") -> pl.Series:
    """Replace characters with mask_char, optionally keeping a prefix/suffix.

    Guarantees at least one masked character when the input is non-empty.
    If keep_prefix + keep_suffix >= len(s), both are scaled down
    proportionally so that at least one character is masked — otherwise
    a short value like "hi" with keep_prefix=5 would leak unchanged.
    """
    if keep_prefix < 0 or keep_suffix < 0:
        raise ValueError("keep_prefix and keep_suffix must be >= 0")

    def _mask(v):
        if v is None:
            return None
        s = str(v)
        n = len(s)
        if n == 0:
            return s
        p = keep_prefix
        q = keep_suffix
        # Enforce the privacy invariant: at least one character is masked.
        # If the caller's prefix+suffix would leave zero masked chars, we
        # shrink them proportionally (rounding down) so 1 char gets masked.
        if p + q >= n:
            # Scale so p + q = n - 1 (at least one char masked).
            target = max(n - 1, 0)
            if p + q > 0:
                scale = target / (p + q)
                p = int(p * scale)
                q = int(q * scale)
            else:
                p = q = 0
        p = min(p, n)
        q = min(q, max(n - p, 0))
        middle = mask_char * (n - p - q)
        return s[:p] + middle + (s[n - q:] if q else "")
    return series.map_elements(_mask, return_dtype=pl.Utf8)


def hmac_hash(series: pl.Series, key: bytes) -> pl.Series:
    """HMAC-SHA256, hex-truncated to 16 chars. Keyed → resists rainbow tables."""
    def _h(v):
        if v is None:
            return None
        digest = hmac.new(key, str(v).encode("utf-8"), hashlib.sha256).hexdigest()
        return digest[:16]
    return series.map_elements(_h, return_dtype=pl.Utf8)


def tokenize(series: pl.Series, key: bytes, prefix: str = "tok_") -> pl.Series:
    """Deterministic-within-session token. Uses HMAC to prevent rainbow tables."""
    def _t(v):
        if v is None:
            return None
        digest = hmac.new(key, str(v).encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{prefix}{digest[:12]}"
    return series.map_elements(_t, return_dtype=pl.Utf8)


def redact(series: pl.Series, replacement: str = "[REDACTED]") -> pl.Series:
    return pl.Series(series.name, [replacement if v is not None else None for v in series],
                     dtype=pl.Utf8)


# --- generalization primitives -----------------------------------------------

def numeric_bin(series: pl.Series, bin_width: float) -> pl.Series:
    """Equal-width binning: value → [lo, lo+width)."""
    if bin_width <= 0:
        raise ValueError("bin_width must be > 0")

    def _bin(v):
        if v is None:
            return None
        lo = (int(v // bin_width)) * bin_width
        hi = lo + bin_width
        return f"[{lo:g}, {hi:g})"
    return series.map_elements(_bin, return_dtype=pl.Utf8)


def date_truncate(series: pl.Series, granularity: str = "month") -> pl.Series:
    """Truncate dates/datetimes to year / month / day."""
    if granularity not in ("year", "month", "day"):
        raise ValueError("granularity must be year/month/day")

    if series.dtype in (pl.Date, pl.Datetime, pl.Time):
        fmt = {"year": "%Y", "month": "%Y-%m", "day": "%F"}[granularity]
        return series.dt.strftime(fmt).alias(series.name)

    def _t(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            d = v.date()
        elif isinstance(v, date):
            d = v
        else:
            return str(v)
        if granularity == "year":
            return f"{d.year:04d}"
        if granularity == "month":
            return f"{d.year:04d}-{d.month:02d}"
        return d.isoformat()
    return series.map_elements(_t, return_dtype=pl.Utf8)


def string_truncate(series: pl.Series, keep: int = 3, pad_char: str = "*") -> pl.Series:
    """Keep first `keep` chars, pad the rest (e.g., ZIP 12345 → 123**)."""
    def _t(v):
        if v is None:
            return None
        s = str(v)
        if len(s) <= keep:
            return s
        return s[:keep] + pad_char * (len(s) - keep)
    return series.map_elements(_t, return_dtype=pl.Utf8)


# --- utility -----------------------------------------------------------------

def new_session_key() -> bytes:
    return secrets.token_bytes(32)
