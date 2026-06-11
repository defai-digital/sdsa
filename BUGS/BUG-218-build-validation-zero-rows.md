# BUG-218: `build_validation` may crash if called with empty DataFrame

- **Classification:** suspected (latent — currently guarded by pipeline)
- **Severity:** MEDIUM
- **File:** `backend/src/sdsa/validate/metrics.py:125-128`
- **Discovered:** 2026-05-04 (round 7)

## Summary

`build_validation()` calls `after.sample(n, seed=0)` where `n = min(10000, after.height)`. If `after.height == 0`, then `n == 0` and `df.sample(0)` may raise a Polars error depending on version. Currently the pipeline guards against zero-row output (raising `PipelineError` before reaching `build_validation`), but the function itself has no protection and would fail if called independently (e.g., in tests or a future code path).

## Evidence

**`validate/metrics.py:125-128`:**
```python
before_sample = before.sample(min(_CORRELATION_SAMPLE, before.height), seed=0) \
    if before.height > _CORRELATION_SAMPLE else before
after_sample = after.sample(min(_CORRELATION_SAMPLE, after.height), seed=0) \
    if after.height > _CORRELATION_SAMPLE else after
```

The conditional `if before.height > _CORRELATION_SAMPLE` skips `sample()` for small DataFrames, passing them through directly. When `height == 0`, the else branch is taken, passing the empty DataFrame to `correlation_matrix()`.

In `correlation_matrix()`:
```python
num_cols = [c for c in df.columns if df[c].dtype.is_numeric()]
```
This returns an empty list for an empty DataFrame with no columns, or still iterates if columns exist but all values are null. The function would return `{}` — which is fine.

However, `compare_column()` at line 71 calls `before.dtype.is_numeric()` which works fine on empty Series. And `_numeric_stats` at line 23 checks `if s.len() == 0 or clean.len() == 0` and returns None stats. So the per-column comparison is safe.

**The actual risk** is in `correlation_matrix` when `num_cols` is non-empty but the DataFrame has 0 rows — `pl.corr("a", "b")` on empty data might return NaN/null, which is handled by the `math.isnan` check.

**Verdict:** Currently safe due to pipeline guards, but `build_validation` lacks its own zero-row protection. If called outside the pipeline (unit test, future API), it could behave unexpectedly.

## Suggested Fix

Add an early return for empty after-DataFrames:

```python
def build_validation(before: pl.DataFrame, after: pl.DataFrame) -> dict[str, Any]:
    if after.height == 0:
        per_col = [compare_column(name, before[name], None) for name in before.columns]
        return {
            "columns": per_col,
            "correlation_before": correlation_matrix(before) if before.height > 0 else {},
            "correlation_after": {},
            "rows_before": before.height,
            "rows_after": 0,
        }
```
