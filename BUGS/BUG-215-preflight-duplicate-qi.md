# BUG-215: Preflight `qi_columns` not deduplicated — causes Polars DuplicateError

- **Classification:** confirmed
- **Severity:** HIGH
- **File:** `backend/src/sdsa/preflight.py:199`
- **Introduced:** initial commit (pre-round-1)
- **Discovered:** 2026-05-04 (round 7)

## Summary

The preflight endpoint builds `qi_columns` without deduplicating, unlike the pipeline which uses `dict.fromkeys()`. If the client sends duplicate policy entries for the same column with `is_quasi_identifier=True`, the resulting `qi_columns` list contains duplicates, causing a Polars `DuplicateError` in `group_by`.

## Evidence

**`preflight.py:199`:**
```python
qi_columns = [p.column for p in request.policies if p.is_quasi_identifier and p.column in df.columns]
```

This list comprehension preserves all occurrences. If policies contains two entries for column `"age"` with `is_quasi_identifier=True`, `qi_columns` becomes `["age", "age"]`.

**Contrast with `pipeline.py:214` (correct):**
```python
qi_cols = list(dict.fromkeys(
    p.column for p in request.policies
    if p.is_quasi_identifier and p.column in df.columns
))
```

The pipeline deduplicates with `dict.fromkeys()`, but preflight does not.

**Trigger path:**
1. Client sends `POST /api/preflight/{session_id}` with policies containing duplicate column entries with `is_quasi_identifier=True`
2. `preflight_k_anonymity()` builds `qi_columns` with duplicates
3. `enforce_k()` calls `df.group_by(qi_columns)` → Polars raises `DuplicateError`
4. The error is caught as `PolicyApplicationError` and returned as HTTP 400

## Suggested Fix

Apply the same `dict.fromkeys()` deduplication that `pipeline.py` uses:

```python
qi_columns = list(dict.fromkeys(
    p.column for p in request.policies
    if p.is_quasi_identifier and p.column in df.columns
))
```

This also applies to the earlier `qi_names` set construction at line 155 (set semantics already dedup, so that line is safe, but line 199 is vulnerable).
