# Frontend Bug Analysis

**Files analyzed:**
- `frontend/index.html` (369 lines)
- `frontend/app.js` (1081 lines)
- `frontend/style.css` (1153 lines)

**Date:** 2026-05-01

---

## Bug 1: Duplicate `change` event listeners on `#columns-table` cause 2x API calls

**File:** `app.js:376-380` and `app.js:684-689`
**Severity:** Medium

**Description:**
Two separate `change` listeners are registered on `#columns-table`. The first (line 376) toggles the `dp-on` CSS class when the action `<select>` changes. The second (line 684) calls `schedulePreflight()` and `schedulePreview()` for any change in the table body. When the action dropdown changes, **both** listeners fire — the second one unconditionally schedules preflight+preview. The first listener does not schedule anything, so there is no duplication from it alone. However, the third listener at line 933 also handles `col-include` changes and schedules preflight+preview independently.

On closer review: listener 1 (line 376) only toggles `dp-on`. Listener 2 (line 684) skips `.col-include` but schedules preflight/preview for all other changes including `.action`. Listener 3 (line 933) handles `.col-include` and also schedules preflight/preview. For `.action` changes, only listener 2 fires the API calls. For `.col-include`, only listener 3 fires. So there is no actual duplication. **Retracted — not a bug.**

---

## Bug 2: Session timer expiry does not warn user or reset UI

**File:** `app.js:63-66`
**Severity:** Low

**Description:**
When the session countdown timer reaches 0, the interval is cleared and the display freezes at `0:00`. No user-facing action is taken — the session has expired server-side, but the UI remains on the configure step. The user can continue editing column policies and click Process, which will fail with a 404 error. The user sees a confusing error message instead of being proactively informed.

**Suggested fix:**
```javascript
if (remaining <= 0) {
  clearInterval(sessionInterval);
  sessionInterval = null;
  showError("Session expired — please re-upload.");
  resetToUpload();
}
```

---

## Bug 3: In-flight upload XHR cannot be cancelled on reset

**File:** `app.js:162-198`
**Severity:** Low

**Description:**
The `XMLHttpRequest` is created inside `uploadXHR()` as a local variable. If the user clicks "Restart" or the "Upload" stepper during an active upload, `resetToUpload()` clears state but cannot abort the in-flight request. When the XHR response eventually arrives, the `uploadFile()` `try` block executes: it sets `state.sessionId`, renders the configure step, and navigates away from upload — all after the user explicitly requested a reset.

**Suggested fix:**
Store the XHR reference so it can be aborted:
```javascript
let activeXHR = null;

function uploadXHR(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    activeXHR = xhr;
    // ... existing listeners ...
    xhr.addEventListener("load", () => { activeXHR = null; /* ... */ });
    xhr.addEventListener("error", () => { activeXHR = null; reject(...); });
    xhr.addEventListener("abort", () => { activeXHR = null; reject(...); });
    // ...
  });
}

// In resetToUpload():
if (activeXHR) { activeXHR.abort(); activeXHR = null; }
```

---

## Bug 4: `⌘O` keyboard shortcut shown in UI but not implemented

**File:** `index.html:66`, `app.js` (missing handler)
**Severity:** Low

**Description:**
The upload card displays `<span class="kbd">⌘O</span>` with the text "to browse", implying a keyboard shortcut. No `keydown` listener for `⌘O` / `Ctrl+O` is registered anywhere in `app.js`. Pressing `⌘O` triggers the browser's native "Open File" dialog (in most browsers), which bypasses the app's file validation logic (`looksLikeSupported`, size check). On browsers where `⌘O` is not intercepted, nothing happens at all, making the hint misleading.

**Suggested fix:**
Either implement the shortcut:
```javascript
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "o") {
    e.preventDefault();
    fileInput.click();
  }
});
```
Or remove the `<span class="kbd">⌘O</span>` and `<span class="muted">to browse</span>` from `index.html:66-67`.

---

## Bug 5: Tooltip position uses potentially stale dimensions

**File:** `app.js:1046-1061`
**Severity:** Low

**Description:**
In the tooltip `show()` function, `tip.textContent = text` is set at line 1049, then `tipRect = tip.getBoundingClientRect()` is called at line 1054 to compute the tooltip width for centering. The tooltip element has `opacity: 0` and `max-width: 280px` via CSS. Since `getBoundingClientRect()` returns layout dimensions (not visual ones), `opacity: 0` does not affect it. However, setting `textContent` does not guarantee a synchronous layout recalculation in all cases — the browser may return stale dimensions from before the text change, causing incorrect horizontal centering.

**Suggested fix:**
Force a reflow between setting content and reading dimensions:
```javascript
tip.textContent = text;
tip.classList.add("visible");
tip.setAttribute("aria-hidden", "false");
void tip.offsetWidth;  // force reflow
const tipRect = tip.getBoundingClientRect();
```

---

## Bug 6: `san[i][j]` index misalignment with dropped columns in preview

**File:** `app.js:800-816`
**Severity:** Medium

**Description:**
In `renderPreviewSanitized()`, the code iterates over `cols` (the full column list including dropped columns) and accesses `san[i][j]` using the same index `j`. For dropped columns, it renders `[dropped]` instead of accessing `san[i][j]`. However, if the backend's sanitized response already excludes dropped columns from the `sanitized` array (so `san[i]` has fewer elements than `cols`), then for every dropped column, all subsequent non-dropped columns will read from the wrong index in `san[i]`.

Example: if columns are `[A, B, C]`, B is dropped, and `san[i] = ["a'", "c'"]` (B already excluded), then:
- `j=0` → `san[i][0]` = `"a'"` ✓
- `j=1` → dropped → `[dropped]` ✓
- `j=2` → `san[i][2]` = `undefined` ✗ (should be `"c'"`)

This would render `undefined` in the preview table for every column after the first dropped column.

**Suggested fix:**
Use a separate sanitized-column index:
```javascript
${cols.map((c, j) => {
  if (dropped.has(c)) return `<td class="dropped">[dropped]</td>`;
  const sanIdx = j - [...cols.slice(0, j)].filter(cc => dropped.has(cc)).length;
  const sv = san[i][sanIdx];
  // ...
}).join("")}
```

Or precompute a mapping array before the loop.

**Caveat:** This bug only manifests if the backend excludes dropped columns from the sanitized rows. If the backend pads them with `null`, the current code works correctly. Verify the backend contract.

---

## Summary Table

| # | File | Line(s) | Severity | Description |
|---|------|---------|----------|-------------|
| 2 | `app.js` | 63–66 | Low | Session timer expiry does not warn user or redirect |
| 3 | `app.js` | 162–198 | Low | In-flight upload XHR not cancellable on reset |
| 4 | `index.html` / `app.js` | 66 | Low | `⌘O` shortcut displayed but never implemented |
| 5 | `app.js` | 1046–1061 | Low | Tooltip width may be stale before forced reflow |
| 6 | `app.js` | 800–816 | Medium | `san[i][j]` index misalignment if dropped columns are excluded from sanitized rows |

**No critical or high-severity bugs found.** The codebase demonstrates good practices: XSS protection via `esc()`, proper use of `textContent` for error toasts, race-condition guards via sequence counters (`preflightSeq`, `previewSeq`), debounced API calls, and graceful session-expiry handling on API responses. The identified issues are all low-to-medium severity UX edge cases and potential data-mapping bugs.
