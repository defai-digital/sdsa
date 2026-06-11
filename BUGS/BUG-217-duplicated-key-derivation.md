# BUG-217: Deterministic key derivation duplicated between preflight and pipeline

- **Classification:** confirmed (code duplication / maintenance hazard)
- **Severity:** MEDIUM
- **Files:** `backend/src/sdsa/preflight.py:142-148`, `backend/src/sdsa/pipeline.py:106-120`
- **Discovered:** 2026-05-04 (round 7)

## Summary

The HMAC key derivation for deterministic mode is implemented twice: once in `pipeline._derive_deterministic_key()` and again inline in `preflight_k_anonymity()`. While both currently produce the same output (`HMAC-SHA256(deployment_salt, "sdsa-det-v1|" + key_name)`), any future change to the derivation (e.g., version bump from `v1` to `v2`) must be applied in both places or preflight estimates will diverge from actual pipeline behavior, breaking the guarantees described in ADR-0008.

## Evidence

**`pipeline.py:106-120`:**
```python
def _derive_deterministic_key(key_name: str, deployment_salt: bytes) -> bytes:
    import hashlib
    import hmac as _hmac
    return _hmac.new(
        deployment_salt,
        b"sdsa-det-v1|" + key_name.encode("utf-8"),
        hashlib.sha256,
    ).digest()
```

**`preflight.py:142-148`:**
```python
if request.deterministic_key_name:
    import hashlib
    import hmac as _hmac
    hmac_key = _hmac.new(
        cfg.deployment_salt,
        b"sdsa-det-v1|" + request.deterministic_key_name.encode("utf-8"),
        hashlib.sha256,
    ).digest()
```

The pipeline also uses the shared `_derive_deterministic_key()` function in `api/routes.py:223` for the preview endpoint, but preflight does not.

## Suggested Fix

Import and reuse `_derive_deterministic_key` from `pipeline.py` in `preflight.py`:

```python
from .pipeline import _derive_deterministic_key

# In preflight_k_anonymity:
if request.deterministic_key_name:
    hmac_key = _derive_deterministic_key(request.deterministic_key_name, cfg.deployment_salt)
```

This ensures a single source of truth for the derivation logic.
