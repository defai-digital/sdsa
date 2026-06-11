# BUG-220: Process endpoint TOCTOU — session can expire between checkout and clear_output

- **Classification:** suspected
- **Severity:** LOW
- **File:** `backend/src/sdsa/api/routes.py:156-162`
- **Discovered:** 2026-05-04 (round 7)

## Summary

In the `process` endpoint, `store.checkout(session_id)` snapshots the session data, but then `store.clear_output(session_id)` is called as a separate operation. Between these two calls, the session could expire and be reaped by the sweeper thread, causing `clear_output` to return `False` and the endpoint to raise a misleading 404 "session not found or expired" — even though the session was valid at checkout time and the user's request was legitimate.

## Evidence

**`routes.py:156-162`:**
```python
snapshot = store.checkout(session_id)
if snapshot is None or snapshot.df is None or snapshot.hmac_key is None:
    raise HTTPException(404, "session not found or expired")

detection = snapshot.detection or {"schema": [], "pii": {}}
if not store.clear_output(session_id):
    raise HTTPException(404, "session not found or expired")
```

The `checkout` at line 156 clones the DataFrame and returns a snapshot. But at line 161, `clear_output` re-looks up the session by ID. If the background sweeper reaped the session between these two calls (window is very small but non-zero), `clear_output` returns `False`.

**Why it's low severity:** The TTL is 30 minutes and the sweeper runs every 60 seconds. The window where this can occur is when the session is already at the edge of expiry. The user would simply need to re-upload.

## Suggested Fix

Since `checkout` already takes a snapshot of the data, the `clear_output` call is mainly about resetting previous output. This could be made atomic by either:

1. Combining checkout+clear into a single store method (e.g., `checkout_and_clear`), or
2. Removing the `clear_output` check and relying on the snapshot data directly, since `store_output` at line 179 already handles the expired-session case.
