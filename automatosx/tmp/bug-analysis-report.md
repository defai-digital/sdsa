# SDSA Bug Analysis Report

**Date:** 2026-04-13  
**Files analyzed:** 20 source files (16 Python, 1 JavaScript, 1 Python sample generator, 2 config/core)  
**Total findings:** 18

---

## Findings by Severity

| Severity | Count |
|----------|-------|
| Critical | 1     |
| High     | 3     |
| Medium   | 6     |
| Low      | 8     |

---

## CRITICAL

### BUG-01: Duplicate QI columns crash the pipeline with unhandled Polars DuplicateError

- **File:** `backend/src/sdsa/pipeline.py:212-213`
- **Category:** Logic / API
- **Severity:** CRITICAL
- **Description:** The API accepts a `policies` list with no uniqueness constraint on column names. If two policies reference the same column as a quasi-identifier, the `qi_cols` list will contain duplicates. This causes `enforce_k()` → `df.group_by(qi_columns)` to raise `polars.exceptions.DuplicateError`, which is NOT caught by any exception handler. The user gets an HTTP 500 with a raw Polars stack trace instead of a meaningful error.

  The frontend never sends duplicates (it iterates unique table rows), but direct API callers or future UI changes could trigger this.

- **Code:**
  ```python
  # pipeline.py:212-213
  qi_cols = [p.column for p in request.policies
             if p.is_quasi_identifier and p.column in df.columns]
  # qi_cols can contain duplicates like ["zip", "zip"]
  
  k_result = enforce_k(df, qi_cols, request.k)  # CRASHES with DuplicateError
  ```

- **Suggested fix:**
  ```python
  # Deduplicate while preserving order
  qi_cols = list(dict.fromkeys(
      p.column for p in request.policies
      if p.is_quasi_identifier and p.column in df.columns
  ))
  ```

---

## HIGH

### BUG-02: LookupError not caught when chardet returns an unsupported encoding

- **File:** `backend/src/sdsa/ingest.py:347-353`
- **Category:** Edge-case / API
- **Severity:** HIGH
- **Description:** `_detect_and_decode()` catches `UnicodeDecodeError` but not `LookupError`. If chardet returns an encoding name that Python's codec registry doesn't recognize (confirmed: `EUC-TW`, `T.61` cause `LookupError`), the error propagates unhandled and produces an HTTP 500.

- **Code:**
  ```python
  # ingest.py:347-353
  try:
      return enc, raw.decode(enc)
  except UnicodeDecodeError as e:
      raise ParseError(
          f"decode failed with encoding {enc!r} near byte {e.start}; "
          "please upload UTF-8 text or a supported legacy encoding"
      ) from e
  # LookupError is NOT caught here!
  ```

- **Suggested fix:**
  ```python
  try:
      return enc, raw.decode(enc)
  except UnicodeDecodeError as e:
      raise ParseError(
          f"decode failed with encoding {enc!r} near byte {e.start}; "
          "please upload UTF-8 text or a supported legacy encoding"
      ) from e
  except LookupError:
      raise ParseError(
          f"detected encoding {enc!r} is not supported; "
          "please upload UTF-8 text"
      ) from None
  ```

---

### BUG-03: Null reference crash in `renderReview` when DOM element is missing

- **File:** `frontend/app.js:995`
- **Category:** Logic / State
- **Severity:** HIGH
- **Description:** `renderReview` accesses `$("claim-box").querySelector(...)` without null-checking `$("claim-box")`. If the HTML is missing the `#claim-box` element (custom deployment, CDN failure, race condition during DOM update), this throws an uncaught `TypeError: Cannot read properties of null`, silently breaking the review page — the user sees a blank step with no error message.

- **Code:**
  ```javascript
  // app.js:995
  const claim = $("claim-box").querySelector(".claim-text");
  claim.innerHTML = `<strong>Privacy claim:</strong> ${esc(report.claim)}`;
  ```

- **Suggested fix:**
  ```javascript
  const claimBox = $("claim-box");
  if (claimBox) {
      const claim = claimBox.querySelector(".claim-text");
      if (claim) claim.innerHTML = `<strong>Privacy claim:</strong> ${esc(report.claim)}`;
  }
  ```

---

### BUG-04: `readErrorMessage` doesn't handle Pydantic 422 validation errors

- **File:** `frontend/app.js:107-115`
- **Category:** API / Data-processing
- **Severity:** HIGH
- **Description:** When the backend rejects a request with Pydantic validation errors (HTTP 422), the `detail` field is a JSON array of objects like `[{"loc":["body","k"],"msg":"...","type":"..."}]`, NOT a string. The check `typeof parsed.detail === "string"` fails, so the function falls through and returns the raw JSON string as the error message. The user sees raw JSON like `[{"type":"greater_than_equal","loc":["body","k"],"msg":"..."}]` instead of a human-readable error.

- **Code:**
  ```javascript
  // app.js:110-113
  try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.detail === "string") return parsed.detail;
      // Falls through to `return raw` — shows raw JSON for 422 errors
  } catch {}
  return raw;
  ```

- **Suggested fix:**
  ```javascript
  try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.detail === "string") return parsed.detail;
      if (Array.isArray(parsed?.detail) && parsed.detail.length > 0) {
          return parsed.detail.map(e => e.msg || String(e)).join("; ");
      }
  } catch {}
  return raw;
  ```

---

## MEDIUM

### BUG-05: Concurrent process requests cause data inconsistency

- **File:** `backend/src/sdsa/api/routes.py:148-166`
- **Category:** State / Race condition
- **Severity:** MEDIUM
- **Description:** The `/process` endpoint first clears output (`store.clear_output`), then runs the pipeline, then stores output. Two concurrent requests for the same session can interleave: Request A clears → B clears → A stores → B stores (overwrites). Request A's client sees A's report JSON in the response body but downloading the CSV yields B's data. The stored report and data are from different runs.

  The frontend disables the button during processing, but the API has no such guard.

- **Code:**
  ```python
  # routes.py:148-166
  store.clear_output(session_id)           # A clears
  result = run_pipeline(...)               # A processes
  # Meanwhile B calls clear_output, processes, stores...
  store.store_output(session_id, ...)      # A stores, then B overwrites
  ```

- **Suggested fix:** Add a per-session processing lock, or use a conditional store (CAS) that fails if output was cleared after the current request started.

---

### BUG-06: `_default_qi` uses `get_config()` on every call — fragile coupling

- **File:** `backend/src/sdsa/policy_config.py:96`
- **Category:** Logic
- **Severity:** MEDIUM
- **Description:** `_default_qi()` calls `get_config().default_k` to compute whether a column should default to QI. This means the QI default depends on a runtime config value, but the frontend independently computes QI defaults using a hardcoded `DEFAULT_K = 5` (app.js:559). If `SDSA_DEFAULT_K` is changed in the environment, the backend and frontend QI suggestions will disagree — the user sees one set of defaults on upload, but the backend would have computed different ones.

- **Code:**
  ```python
  # policy_config.py:96
  return u * get_config().default_k <= n
  ```

- **Suggested fix:** Return the effective `default_k` in the upload response so the frontend can use the same value:
  ```python
  # In UploadResponse, add:
  default_k: int = cfg.default_k
  ```

---

### BUG-07: `checkout` makes shallow copies of nested dicts

- **File:** `backend/src/sdsa/core/session.py:83,85`
- **Category:** State
- **Severity:** MEDIUM
- **Description:** `SessionStore.checkout()` creates a `SessionSnapshot` with `dict(session.detection)` and `dict(session.output_report)`. These are **shallow** copies — nested structures (the `schema` list, `pii` dict, `policy_suggestions` dict) are shared references. Any code that mutates a nested structure through the snapshot would silently corrupt the live session data. Currently the code only reads from snapshots, so this is not an active bug, but it is a fragile invariant that could break with future changes.

- **Code:**
  ```python
  # session.py:83
  detection=dict(session.detection) if session.detection is not None else None,
  # session.py:85
  output_report=dict(session.output_report) if session.output_report is not None else None,
  ```

- **Suggested fix:** Use `copy.deepcopy()` or `import json; json.loads(json.dumps(...))` for nested structures.

---

### BUG-08: SQL sample generator doesn't escape first names

- **File:** `samples/generate.py:318-320`
- **Category:** Data-processing
- **Severity:** MEDIUM
- **Description:** In `gen_sql()`, last names are SQL-escaped (`.replace("'", "''")` on line 319), but first names are NOT escaped on line 318. If `FIRST_NAMES_EN` were extended with a name containing an apostrophe (e.g., "O'Connor"), the generated SQL would have a syntax error or injection. Currently no name in the pool has an apostrophe, but this is a latent bug.

- **Code:**
  ```python
  # generate.py:318-320
  first = rng.choice(FIRST_NAMES_EN)          # NOT escaped
  last = rng.choice(LAST_NAMES_EN).replace("'", "''")  # escaped
  full = f"{first} {last}"
  ```

- **Suggested fix:**
  ```python
  first = rng.choice(FIRST_NAMES_EN).replace("'", "''")
  last = rng.choice(LAST_NAMES_EN).replace("'", "''")
  ```

---

### BUG-09: `enforce_k` skips QI column validation for empty DataFrames

- **File:** `backend/src/sdsa/kanon/enforce.py:33-35`
- **Category:** Edge-case / Logic
- **Severity:** MEDIUM
- **Description:** When `rows_total == 0`, `enforce_k` returns early without checking if `qi_columns` exist in the DataFrame. A caller passing an empty DataFrame with invalid QI column names would get a silent success instead of the expected `ValueError`. This violates the function's documented contract and could mask upstream bugs.

- **Code:**
  ```python
  # enforce.py:33-35
  if not qi_columns or rows_total == 0:
      return KAnonResult(df, rows_total or 0, rows_total, 0, 0.0, 0, 0)
      # ^^^ skips the missing-column validation below
  ```

- **Suggested fix:**
  ```python
  if not qi_columns:
      return KAnonResult(df, rows_total, rows_total, 0, 0.0, 0, 0)
  missing = [c for c in qi_columns if c not in df.columns]
  if missing:
      raise ValueError(f"QI columns not in dataframe: {missing}")
  if rows_total == 0:
      return KAnonResult(df, 0, 0, 0, 0.0, 0, 0)
  ```

---

### BUG-10: Preview route doesn't validate DP epsilon range before applying noise

- **File:** `backend/src/sdsa/api/routes.py:217-226`
- **Category:** Logic / API
- **Severity:** MEDIUM
- **Description:** The preview route checks `cfg.epsilon_min <= eps <= cfg.epsilon_max` (line 225) but this check happens AFTER the LaplaceParams object is constructed (line 218-222). If epsilon is negative or zero, `LaplaceParams.scale` would divide by zero. The `apply_laplace` function catches this (it checks `epsilon <= 0`), but the error is swallowed by the `except ValueError: continue` on line 231-232. The user gets no feedback that their DP config was invalid — they just see the original (un-noised) values in the preview, which could mislead them into thinking DP noise is minimal.

  The Process pipeline properly validates and raises errors, creating an inconsistency between preview and process behavior.

- **Code:**
  ```python
  # routes.py:217-232
  eps = float(params["epsilon"])        # Could be 0 or negative
  lp = LaplaceParams(epsilon=eps, ...)   # Constructs with bad epsilon
  if not (cfg.epsilon_min <= eps <= cfg.epsilon_max):
      continue                           # Silently skips
  try:
      df = df.with_columns(apply_laplace(df[col], lp).alias(col))
  except ValueError:
      continue                           # Silently swallows invalid-epsilon error
  ```

- **Suggested fix:** Move the epsilon range check BEFORE constructing `LaplaceParams`, and add a visual indicator in the preview when DP is skipped.

---

## LOW

### BUG-11: `_histogram` adds `lo` to edges, duplicating the first breakpoint

- **File:** `backend/src/sdsa/validate/metrics.py:43-46`
- **Category:** Data-processing
- **Severity:** LOW
- **Description:** Polars `hist()` returns breakpoints starting from the second bin edge. The code prepends `lo` (the minimum value). When `lo` is exactly equal to the first breakpoint (which it usually is for evenly-spaced data), the first edge is duplicated. This creates an `[lo, lo, bp2, bp3, ...]` edges array with 11 elements for 10 counts, where the first bin has zero width. Downstream consumers might misinterpret this.

- **Code:**
  ```python
  # metrics.py:43-46
  return {
      "edges": [lo] + [float(v) for v in hist["breakpoint"].to_list()],
      "counts": [int(v) for v in hist["count"].to_list()],
  }
  ```

- **Suggested fix:** The edges array should have `len(counts) + 1` elements. The current code produces `11` edges for `10` counts, which is technically correct for standard histogram representation. However, verify that the frontend correctly handles the edge count. No fix needed if the frontend handles it correctly.

---

### BUG-12: Redundant `import math` inside `correlation_matrix`

- **File:** `backend/src/sdsa/validate/metrics.py:96`
- **Category:** Logic (dead code)
- **Severity:** LOW
- **Description:** `math` is already imported at module level (line 10). The re-import on line 96 is redundant.

- **Code:**
  ```python
  # metrics.py:96
  def correlation_matrix(df: pl.DataFrame) -> dict[str, dict[str, float | None]]:
      import math  # REDUNDANT — already imported at line 10
  ```

- **Suggested fix:** Remove the redundant import.

---

### BUG-13: `max(n, 1)` guard is redundant after length check

- **File:** `backend/src/sdsa/detect/pii.py:164`
- **Category:** Logic (dead code)
- **Severity:** LOW
- **Description:** Line 161 already checks `series.len() > 0`, so `n` is always >= 1. The `max(n, 1)` guard on line 164 is redundant. Same pattern in `detect/schema.py:27`.

- **Code:**
  ```python
  # pii.py:161-164
  if series.dtype == pl.Utf8 and series.len() > 0:
      n = series.len()       # n > 0 is guaranteed
      u = series.n_unique()
      if u / max(n, 1) > 0.95 and n > 20 and not candidates:
  ```

- **Suggested fix:** Replace `max(n, 1)` with `n` since it's already guaranteed positive.

---

### BUG-14: `gen_employees_huge` doesn't sanitize first names for CSV

- **File:** `samples/generate.py:362-364`
- **Category:** Data-processing
- **Severity:** LOW
- **Description:** Last names are sanitized (commas and quotes removed on line 363) but first names are not. If a first name contained a comma or double-quote, the generated CSV would be malformed. No current first name has these characters, but it's a latent issue.

- **Code:**
  ```python
  # generate.py:362-363
  first = rng.choice(FIRST_NAMES_EN)                    # NOT sanitized
  last = rng.choice(LAST_NAMES_EN).replace(",", "").replace("\"", "")  # sanitized
  ```

- **Suggested fix:** Apply the same sanitization to first names:
  ```python
  first = rng.choice(FIRST_NAMES_EN).replace(",", "").replace("\"", "")
  ```

---

### BUG-15: `_parse_column_list` doesn't handle nested square brackets

- **File:** `backend/src/sdsa/ingest.py:124-144`
- **Category:** Edge-case
- **Severity:** LOW
- **Description:** The column list parser treats `[` as a quote start with `]` as the quote end. For a column name like `[dbo].[col]` in a SQL INSERT column list, the parser would stop at the first `]`, producing `dbo` instead of `dbo.col`. This is an edge case for SQL Server-style bracketed identifiers.

- **Code:**
  ```python
  # ingest.py:136-137
  if ch in {'"', "`", "["}:
      quote = "]" if ch == "[" else ch
  # Stops at first ']' — doesn't handle [schema].[table] patterns
  ```

- **Suggested fix:** This is a known limitation. A full fix would require more sophisticated parsing of dotted bracketed identifiers.

---

### BUG-16: `detect_encoding` function is unused

- **File:** `backend/src/sdsa/ingest.py:32-46`
- **Category:** Logic (dead code)
- **Severity:** LOW
- **Description:** The `detect_encoding()` function (lines 32-46) is never called anywhere in the codebase. It was superseded by `_detect_and_decode()` but was left behind. The code comment on lines 329-335 explains the replacement.

- **Code:**
  ```python
  # ingest.py:32-46
  def detect_encoding(raw: bytes) -> str:  # UNUSED — replaced by _detect_and_decode
      ...
  ```

- **Suggested fix:** Remove `detect_encoding()` or mark it as deprecated.

---

### BUG-17: SQL parse result sets `encoding=""` instead of the detected encoding

- **File:** `backend/src/sdsa/ingest.py:63,104,313`
- **Category:** Data-processing
- **Severity:** LOW
- **Description:** Individual parsers (`parse_csv`, `parse_txt`, `parse_sql`) set `encoding=""` in their `ParseResult`. The actual encoding is only filled in by `parse_upload()` at line 372, which overrides it. This means the intermediate ParseResult objects always have an empty encoding, which is not a bug but could confuse someone reading the code or calling the parsers directly.

- **Code:**
  ```python
  # ingest.py:63
  return ParseResult(df=df, format="csv", encoding="", meta={"delimiter": ","})
  # ingest.py:313
  return ParseResult(df=df, format="sql", encoding="", meta={...})
  ```

- **Suggested fix:** Document that `encoding=""` is a placeholder, or have `parse_upload` pass the encoding down to the individual parsers.

---

### BUG-18: Frontend `session_ttl_seconds` of 0 would be treated as 1800

- **File:** `frontend/app.js:56`
- **Category:** Edge-case
- **Severity:** LOW
- **Description:** `const ttlSeconds = state.uploadData?.session_ttl_seconds || 1800;` — if the server were configured with `SDSA_SESSION_TTL=0`, the falsy check `|| 1800` would override it to 1800. The session timer would show 30 minutes remaining when the session actually expires immediately.

- **Code:**
  ```javascript
  // app.js:56
  const ttlSeconds = state.uploadData?.session_ttl_seconds || 1800;
  ```

- **Suggested fix:** Use nullish coalescing:
  ```javascript
  const ttlSeconds = state.uploadData?.session_ttl_seconds ?? 1800;
  ```

---

## Summary Table

| # | File | Line | Category | Severity | Description |
|---|------|------|----------|----------|-------------|
| 01 | pipeline.py | 212 | Logic/API | CRITICAL | Duplicate QI columns crash with Polars DuplicateError (500) |
| 02 | ingest.py | 348 | Edge-case | HIGH | LookupError not caught for unsupported chardet encodings |
| 03 | app.js | 995 | Logic | HIGH | Null reference crash in renderReview on missing DOM element |
| 04 | app.js | 107 | API | HIGH | readErrorMessage doesn't handle Pydantic 422 array detail |
| 05 | routes.py | 148 | State/Race | MEDIUM | Concurrent process requests cause data inconsistency |
| 06 | policy_config.py | 96 | Logic | MEDIUM | QI default uses server config; frontend hardcodes DEFAULT_K=5 |
| 07 | session.py | 83 | State | MEDIUM | Shallow copy in checkout shares nested structures |
| 08 | generate.py | 320 | Data | MEDIUM | SQL first names not escaped — latent SQL injection in samples |
| 09 | enforce.py | 33 | Edge-case | MEDIUM | Empty df skips QI column validation |
| 10 | routes.py | 217 | Logic/API | MEDIUM | Preview silently swallows invalid DP epsilon |
| 11 | metrics.py | 43 | Data | LOW | Histogram edges may duplicate the first breakpoint |
| 12 | metrics.py | 96 | Dead code | LOW | Redundant `import math` |
| 13 | pii.py | 164 | Dead code | LOW | `max(n, 1)` redundant after `len() > 0` check |
| 14 | generate.py | 362 | Data | LOW | Huge CSV generator doesn't sanitize first names |
| 15 | ingest.py | 124 | Edge-case | LOW | SQL column parser doesn't handle nested brackets |
| 16 | ingest.py | 32 | Dead code | LOW | `detect_encoding()` is unused (superseded) |
| 17 | ingest.py | 63 | Data | LOW | Parsers set `encoding=""` as placeholder |
| 18 | app.js | 56 | Edge-case | LOW | Session TTL of 0 treated as 1800 (falsy vs nullish) |

---

## Recommended Fix Priority

1. **BUG-01** (CRITICAL) — One-line fix, prevents 500 errors from direct API calls
2. **BUG-02** (HIGH) — Two-line fix, handles rare but real encoding failures
3. **BUG-04** (HIGH) — Five-line fix, improves error UX for all validation errors
4. **BUG-03** (HIGH) — Three-line fix, prevents blank review page
5. **BUG-05** (MEDIUM) — Requires design decision on concurrency model
6. **BUG-10** (MEDIUM) — Reorder validation to match process pipeline
7. **BUG-08, 14** (MEDIUM/LOW) — Quick fixes in sample generator
8. **BUG-06, 07, 09** (MEDIUM) — Design improvements
9. **BUG-11–18** (LOW) — Cleanup and defensive hardening
