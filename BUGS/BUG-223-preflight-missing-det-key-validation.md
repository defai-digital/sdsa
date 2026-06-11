# BUG-223: PreflightRequest missing `deterministic_key_name` length validation

- **Classification:** confirmed
- **Severity:** LOW
- **File:** `backend/src/sdsa/preflight.py:21`
- **Discovered:** 2026-05-04 (round 8)

## Summary

`ProcessRequest` validates `deterministic_key_name` with `min_length=1, max_length=256`, but `PreflightRequest` declares it as `str | None = None` with no constraints. A client can send an empty string to preflight (which would silently derive a key for the empty name) or a very long string. While not a security vulnerability (the HMAC derivation handles arbitrary-length input), it creates an inconsistency: preflight accepts inputs that Process would reject.

## Evidence

**`pipeline.py:32` (correct):**
```python
deterministic_key_name: str | None = Field(default=None, min_length=1, max_length=256)
```

**`preflight.py:21` (missing validation):**
```python
deterministic_key_name: str | None = None
```

**Trigger path:**
1. Client sends `POST /api/preflight/{session_id}` with `deterministic_key_name: ""` (empty string)
2. Preflight accepts it, derives HMAC key for empty name, returns preflight estimate
3. Client clicks Process → `POST /api/process/{session_id}` with same payload
4. Pydantic rejects `deterministic_key_name: ""` due to `min_length=1` → 422 validation error
5. User sees a confusing error after preflight showed success

## Suggested Fix

Add the same field constraints to `PreflightRequest`:

```python
deterministic_key_name: str | None = Field(default=None, min_length=1, max_length=256)
```
