# BUG-226: Frontend global event listeners never cleaned up on session reset — memory leak in SPA

Classification: confirmed

## Summary

The frontend registers multiple event listeners on `document` and `window` that are never removed when sessions are reset or the user navigates back to the upload step. In a long-lived SPA session with many upload/configure cycles, these listeners accumulate, causing memory leaks and potential duplicate event handling.

## Evidence

**File:** `frontend/app.js` — listeners registered at module load time, never removed:

| Line | Target | Event | Purpose |
|------|--------|-------|---------|
| 169 | `xhr.upload` | `progress` | Upload progress bar |
| 172 | `xhr.upload` | `load` | Indeterminate progress after upload |
| 177 | `xhr` | `load` | Upload response handler |
| 194 | `xhr` | `error` | Upload error handler |
| 195 | `xhr` | `abort` | Upload abort handler |
| 385 | `document` | `change` | Sync dp-on class with action dropdown |
| 500 | `document` | `click` | Quick-fix remediation buttons |
| 883 | `.preview-tab` | `click` | Preview tab switching |
| 1055 | `.step-item[data-step="upload"]` | `click` | Reset to upload |
| 1056 | `.step-item[data-step="upload"]` | `keydown` | Reset to upload (keyboard) |
| 1088 | `document` | `mouseover` | Tooltip show |
| 1092 | `document` | `mouseout` | Tooltip hide |
| 1095 | `document` | `focusin` | Tooltip show (a11y) |
| 1099 | `document` | `focusout` | Tooltip hide (a11y) |
| 1102 | `window` | `scroll` | Tooltip hide |

The XHR listeners (lines 169-195) are per-request and are GC'd when the XHR object is discarded — those are fine. But the `document` and `window` listeners (lines 385, 500, 883, 1055-1056, 1088-1102) are registered once at module load and persist for the lifetime of the page.

Most of these are **intentionally** global (delegated event handling for dynamically-created elements). However, the tooltip listeners (lines 1088-1102) and the step-click listeners (lines 1055-1056) are registered inside IIFEs or `forEach` callbacks without any cleanup path.

The real issue is the **step-click listeners** (lines 1051-1062):

```javascript
document.querySelectorAll('.step-item[data-step="upload"]').forEach((el) => {
  el.setAttribute("role", "button");
  el.setAttribute("tabindex", "0");
  el.classList.add("step-clickable");
  el.addEventListener("click", resetToUpload);
  el.addEventListener("keydown", (e) => { ... });
});
```

If the DOM is re-rendered (e.g., the step bar is rebuilt), this code would need to run again, creating duplicate listeners. Currently the step bar is not re-rendered, so this is a latent bug — if the step bar HTML is ever regenerated, listeners will stack.

## Impact

- **Current impact:** Low. Most global listeners are intentional delegated handlers that should persist.
- **Latent risk:** If the step bar or preview tabs are ever re-rendered dynamically, duplicate listeners will accumulate, causing `resetToUpload` to fire multiple times per click.
- **Memory:** Negligible for the current codebase (~15 persistent listeners).

## Suggested Fix

For the step-click listeners, use event delegation instead of per-element listeners:

```javascript
document.addEventListener("click", (e) => {
  if (e.target.closest('.step-item[data-step="upload"]')) {
    resetToUpload();
  }
});
```

This consolidates into the existing document-level click handler (line 500) and avoids per-element listener registration.

## Related

- BUG-225: Same category of timer/listener lifecycle management in the frontend.
