# BUG-221: Preflight DP path leaks PII cell values in error messages for non-numeric columns

- **Classification:** confirmed
- **Severity:** MEDIUM
- **File:** `backend/src/sdsa/preflight.py:193-197`
- **Discovered:** 2026-05-04 (round 8)

## Summary

The pipeline validates that a DP Laplace column is numeric *before* calling `apply_laplace`, producing a clean error message. The preflight endpoint skips this check. When a non-numeric column (e.g., Utf8/string) is configured for `dp_laplace` and also marked as a quasi-identifier, `apply_laplace` calls `float(v)` on string cell values, which raises a `ValueError` containing the actual cell content (e.g., `"could not convert string to float: 'John'"`). This PII-containing error message propagates back to the client via the preflight API response.

## Evidence

**`preflight.py:167-197` — no numeric dtype check before `apply_laplace`:**
```python
for col in dp_columns:
    if col not in df.columns or col not in qi_names:
        continue
    # ... epsilon/bounds validation ...
    try:
        noised = apply_laplace(df[col], LaplaceParams(eps, lower, upper))
    except ValueError as e:
        raise PolicyApplicationError(f"invalid DP params for '{col}': {e}") from e
```

**Contrast with `pipeline.py:191-195` (correct):**
```python
if not df[col].dtype.is_numeric():
    raise PipelineError(
        f"column '{col}' has dtype {df[col].dtype}; dp_laplace requires "
        f"a numeric column"
    )
```

**Trigger path:**
1. Client sends `POST /api/preflight/{session_id}` with a string column configured as both `action: "dp_laplace"` and `is_quasi_identifier: true`
2. Preflight processes QI columns, reaches the DP pass for this column
3. `apply_laplace(df[col], ...)` calls `series.map_elements(_noise, ...)` where `_noise` does `float(v)` on each value
4. `float("John")` raises `ValueError("could not convert string to float: 'John'")`
5. Preflight catches this: `PolicyApplicationError("invalid DP params for 'name': could not convert string to float: 'John'")`
6. Error is returned as HTTP 400 response body — PII cell value exposed to client

**Note:** This only triggers when the column is both `dp_laplace` and `is_quasi_identifier`, because preflight's DP loop (line 167) only processes columns in `qi_names`.

## Suggested Fix

Add the same numeric dtype check the pipeline uses, before calling `apply_laplace`:

```python
if not df[col].dtype.is_numeric():
    raise PolicyApplicationError(
        f"column '{col}' has dtype {df[col].dtype}; dp_laplace requires "
        f"a numeric column"
    )
```

This should be inserted in `preflight.py` after the bounds validation and before the `apply_laplace` call (around line 193).
