# BUG-224: `_md_escape` does not escape `<` and `>` — XSS in markdown report

Classification: suspected

## Summary

The `_md_escape()` function in `backend/src/sdsa/report.py` escapes common markdown special characters (`\`, `` ` ``, `*`, `_`, `[`, `]`, `(`, `)`, `#`, `|`) but does **not** escape `<` and `>`. If a user-uploaded column name contains HTML-like content (e.g., `<img onerror=alert(1)>`), it will be rendered as raw HTML when the markdown report is viewed in an HTML markdown renderer.

## Evidence

**File:** `backend/src/sdsa/report.py:57-61`

```python
def _md_escape(s: str) -> str:
    """Escape markdown special characters in user-controlled strings."""
    for ch in ('\\', '`', '*', '_', '[', ']', '(', ')', '#', '|'):
        s = s.replace(ch, '\\' + ch)
    return s
```

The character set does not include `<` or `>`. This function is used on:
- Column names (line 83, 92): ``f"- `{_md_escape(col)}`: Laplace, ε = {eps}"``
- Policy column names (line 92): ``f"- `{_md_escape(p['column'])}`: {p['action']}{qi}"``
- Deterministic key name (line 96): ``f"- key name: `{_md_escape(report['deterministic_mode']['key_name'])}`"``

Column names come from user-uploaded files and are fully user-controlled.

## Impact

When the markdown report (`/download/{session_id}/report.md`) is rendered in a browser-based markdown viewer (e.g., GitHub, VS Code preview, or any HTML markdown renderer), unescaped `<` and `>` in column names can inject HTML/JavaScript. This is a stored XSS vector scoped to the report download.

## Suggested Fix

Add `<` and `>` to the escape set in `_md_escape`:

```python
def _md_escape(s: str) -> str:
    for ch in ('\\', '`', '*', '_', '[', ']', '(', ')', '#', '|', '<', '>'):
        s = s.replace(ch, '\\' + ch)
    return s
```

## Related

- BUG-214 (closed): Frontend `esc()` already escapes `<` and `>` — this bug is the backend counterpart that was missed.
