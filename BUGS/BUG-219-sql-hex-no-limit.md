# BUG-219: SQL parser allows arbitrarily large hex literals without size limit

- **Classification:** suspected
- **Severity:** LOW
- **File:** `backend/src/sdsa/ingest.py:185-188`
- **Discovered:** 2026-05-04 (round 7)

## Summary

The SQL `_parse_value()` function accepts `0x`-prefixed hex tokens and converts them to Python integers via `int(token, 16)` with no length limit. A maliciously crafted SQL dump with a multi-megabyte hex literal could cause excessive memory consumption during parsing.

## Evidence

**`ingest.py:185-188`:**
```python
if upper.startswith("0X"):
    try:
        return int(token, 16), i
    except ValueError:
        pass
```

A token like `0X` followed by millions of hex digits would create a very large Python integer. While Python handles arbitrary precision integers, the memory allocation for a huge number could be significant.

## Suggested Fix

Add a reasonable length limit for hex literals (e.g., 16 chars = 64-bit max):

```python
if upper.startswith("0X"):
    if len(token) > 18:  # "0x" + 16 hex digits
        raise ParseError(f"hex literal too large in VALUES: {token[:20]}...")
    try:
        return int(token, 16), i
    except ValueError:
        pass
```
