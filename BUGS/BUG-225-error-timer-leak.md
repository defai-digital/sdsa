# BUG-225: Frontend `showError` and `flashDropzoneError` setTimeout timers leak — race condition in error display

Classification: confirmed

## Summary

Two frontend functions use `setTimeout` to auto-hide error messages but never store or clear the timer IDs. If errors are triggered in rapid succession (e.g., during a failed upload followed by a session-expired reset), old timers fire and hide newer error messages prematurely.

## Evidence

**File:** `frontend/app.js:72-77`

```javascript
const showError = (msg) => {
  const el = $("error");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 8000);  // timer ID not stored
};
```

**File:** `frontend/app.js:257-261`

```javascript
function flashDropzoneError(msg) {
  dropzone.classList.add("error");
  $("dropzone-file").textContent = msg;
  setTimeout(() => dropzone.classList.remove("error"), 2000);  // timer ID not stored
}
```

Neither function stores the return value of `setTimeout`, and neither clears a previous timer before setting a new one. This means:

1. If `showError("A")` is called, then `showError("B")` is called 1 second later, the first timer will fire 7 seconds later and hide the error banner — even though error "B" was shown only 7 seconds ago and should remain visible for 8 seconds.
2. Multiple concurrent timers accumulate in the event loop.

## Impact

- Users may see error messages disappear before they have time to read them.
- In race conditions (session expiry + upload failure), the wrong error may be hidden while a different one is still relevant.
- Low-severity UX bug; does not affect data integrity or security.

## Suggested Fix

Store timer IDs and clear previous timers:

```javascript
let errorTimer = null;
const showError = (msg) => {
  const el = $("error");
  if (errorTimer) { clearTimeout(errorTimer); errorTimer = null; }
  el.textContent = msg;
  el.classList.remove("hidden");
  errorTimer = setTimeout(() => { el.classList.add("hidden"); errorTimer = null; }, 8000);
};
```

Same pattern for `flashDropzoneError`.

## Related

- BUG-106 (fixed): `resetToUpload()` clears `preflightTimer` — same pattern should apply to error timers.
- BUG-116 (fixed): `resetPreviewPanel()` resets `previewSeq` — same discipline for timer management.
