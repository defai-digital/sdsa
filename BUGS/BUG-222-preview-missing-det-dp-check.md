# BUG-222: Preview endpoint doesn't enforce deterministic+DP exclusion (ADR-0008)

- **Classification:** confirmed
- **Severity:** MEDIUM
- **File:** `backend/src/sdsa/api/routes.py:220-263`
- **Discovered:** 2026-05-04 (round 8)

## Summary

Both the pipeline (`pipeline.py:137-140`) and preflight (`preflight.py:133-136`) enforce the ADR-0008 constraint that deterministic mode cannot be combined with DP Laplace columns. The preview endpoint skips this validation entirely. A user can successfully preview a configuration with both `deterministic_key_name` and DP columns, but will get a 400 error on Process — creating an inconsistent experience where the preview lies about what will succeed.

## Evidence

**`pipeline.py:137-140` (correct):**
```python
dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
if request.deterministic_key_name and dp_columns:
    raise PipelineError(
        "Deterministic mode cannot be combined with DP columns (ADR-0008)."
    )
```

**`preflight.py:133-136` (correct):**
```python
dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
if request.deterministic_key_name and dp_columns:
    raise PolicyApplicationError(
        "Deterministic mode cannot be combined with DP columns (ADR-0008)."
    )
```

**`routes.py:219-263` (missing check):**
```python
hmac_key = snapshot.hmac_key
if request.deterministic_key_name:
    if cfg.deployment_salt_is_ephemeral:
        raise HTTPException(400, "...")
    hmac_key = _derive_deterministic_key(request.deterministic_key_name, cfg.deployment_salt)

df = head.clone()
dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
# ← No check for deterministic_key_name and dp_columns together

try:
    for p in request.policies:
        df = apply_policy(df, p, hmac_key)
    # ... DP noise applied ...
```

**Trigger path:**
1. Client sends `POST /api/preview/{session_id}` with both `deterministic_key_name` set and at least one policy with `action: "dp_laplace"`
2. Preview succeeds and shows sanitized output with DP noise + deterministic HMAC
3. Client clicks Process → `POST /api/process/{session_id}` → gets 400 "Deterministic mode cannot be combined with DP columns"
4. User is confused because preview worked fine

## Suggested Fix

Add the same exclusion check at the start of the preview handler, after `dp_columns` is computed:

```python
dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
if request.deterministic_key_name and dp_columns:
    raise HTTPException(
        400,
        "Deterministic mode cannot be combined with DP columns (ADR-0008)."
    )
```
