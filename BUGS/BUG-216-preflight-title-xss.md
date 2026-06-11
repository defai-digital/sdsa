# BUG-216: `renderPreflight` injects server data into innerHTML without escaping

- **Classification:** suspected
- **Severity:** MEDIUM
- **File:** `frontend/app.js:492`
- **Discovered:** 2026-05-04 (round 7)

## Summary

The `renderPreflight()` function builds an HTML string with `el.innerHTML = ...` and inserts the `summary` and `meta` variables without passing them through `esc()`. While these are currently constructed from numeric server values, any future change that puts user- or server-controlled string content into these variables would create an XSS vector. The same pattern is consistently escaped elsewhere in the codebase (e.g., `bullets` are `esc(msg)`-wrapped).

## Evidence

**`app.js:491-493`:**
```javascript
el.innerHTML = `
    <div class="preflight-title">${summary}</div>
    <div class="meta">k=${preflight.k} · ...</div>
```

The `summary` variable is constructed at lines 445-447:
```javascript
const summary = preflight.qi_columns.length
    ? `Estimated suppression: ${(preflight.suppression_ratio * 100).toFixed(1)}% (${preflight.rows_suppressed}/${preflight.rows_total} rows)`
    : "No QI columns selected; k-anonymity will not suppress rows.";
```

Currently `summary` contains only numeric interpolations and string literals. However, `qi_columns` is an array of column names from the server (e.g., `preflight.qi_columns.join(", ")` is not used here, but could be in a refactor). The `meta` div directly interpolates numeric values, which is safe today.

**Contrast with line 495** where `bullets` are properly escaped:
```javascript
${bullets.map((msg) => `<li>${esc(msg)}</li>`).join("")}
```

## Suggested Fix

Wrap `summary` and `meta` in `esc()` for defense-in-depth:

```javascript
el.innerHTML = `
    <div class="preflight-title">${esc(summary)}</div>
    <div class="meta">${esc(metaText)}</div>
`;
```

This ensures the pattern remains safe even if future changes introduce string content from server responses.
