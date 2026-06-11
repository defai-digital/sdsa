# LOW Bug Report Review Results

Reviewed: 2026-05-03

## Summary
- Total bugs requested: 57
- Report files found: 37
- Report files NOT found (N/A): 20
- Confirmed: 37
- False positive: 0

---

## Detailed Results

| # | Verdict | Reasoning |
|---|---------|-----------|
| 036 | **confirmed** | Code at `enforce.py:51-54` matches exactly: try/except fallback between `nulls_equal=True` and `join_nulls=True` is present. Theoretical future-Polars risk is real. |
| 041 | **confirmed** | Code at `preflight.py:75-116` matches. The while loop can reduce `current_qis` to `[]`, producing `reaches_target=True` with zero QI columns. |
| 042 | **N/A** | Report file does not exist in BUGS/ directory. |
| 043 | **confirmed** | Code at `ingest.py:196` falls through to `return token, i` for unrecognized tokens. Line reference is slightly off (reports line 215, actual function starts at 161) but behavior is accurate. |
| 044 | **N/A** | Report file does not exist in BUGS/ directory. |
| 045 | **N/A** | Report file does not exist in BUGS/ directory. |
| 046 | **confirmed** | Code at `main.py:57` shows `allow_headers=["Content-Type"]`. Auth headers not included — forward-compatibility trap is real. |
| 078 | **confirmed** | Code at `ingest.py:40` and `:81` both use `except Exception as e:` in CSV/TXT parsers. Matches report exactly. |
| 079 | **N/A** | Report file does not exist in BUGS/ directory. |
| 080 | **N/A** | Report file does not exist in BUGS/ directory. |
| 081 | **N/A** | Report file does not exist in BUGS/ directory. |
| 082 | **N/A** | Report file does not exist in BUGS/ directory. |
| 083 | **N/A** | Report file does not exist in BUGS/ directory. |
| 084 | **N/A** | Report file does not exist in BUGS/ directory. |
| 085 | **confirmed** | Code at `samples/generate.py:362` shows `first = rng.choice(FIRST_NAMES_EN)` without sanitization, while line 363 sanitizes `last`. Matches exactly. |

| 095 | **confirmed** | Code at `routes.py:186-242` applies DP noise but intentionally skips k-anonymity (confirmed by comment at line 190-191). The UX concern about pre-suppression noise distribution is valid. |
| 114 | **confirmed** | Code at `app.js:75-80` shows `showError` creates `setTimeout` without storing/clearing the ID. Timer stacking is real. |
| 115 | **confirmed** | Code at `app.js:164-199` creates XHR inside a Promise closure; it is never exposed for abort. `resetToUpload()` cannot cancel in-flight uploads. |
| 116 | **confirmed** | Code at `app.js:728-730` shows `resetPreviewPanel()` does NOT increment `previewSeq`. An in-flight preview fetch from a previous session could pass the stale-sequence check. |
| 117 | **confirmed** | Code at `app.js:133-137` shows `fmtBytes(n)` has no guard for negative, NaN, or Infinity. Matches report. |
| 118 | **confirmed** | Code at `app.js:621-639` shows `btn.disabled = true` at line 639, after `collectProcessPayload()` at line 622. A rapid double-click can execute payload collection twice before the button is disabled. |
| 119 | **N/A** | Report file does not exist in BUGS/ directory. |
| 120 | **N/A** | Report file does not exist in BUGS/ directory. |
| 121 | **N/A** | Report file does not exist in BUGS/ directory. |
| 122 | **confirmed** | Code at `app.js:1031-1032` and `:1039` calls `resetToUpload` (async) without `await` or `.catch()`. Unhandled rejections possible. |
| 125 | **confirmed** | Code at `pii.py:98` shows only 4 regions: `(None, "US", "TW", "GB")`. Matches report exactly. |
| 129 | **confirmed** | All described code patterns are present: `float(clean.min())` at `metrics.py:28-29`, `join_nulls=True` at `enforce.py:54`, `int(...min()...)` at `enforce.py:65`, untyped dict access in `preflight.py` sort keys. |
| 136 | **confirmed** | Code at `ingest.py:277-282` shows the exact error message. Tables dict keyed by `(table_name, columns_tuple)`, so same-table different-column INSERTs produce "multi-table" error listing only one table name. |
| 137 | **confirmed** | Code at `pipeline.py:157-167` appends to `policies_applied` unconditionally. `apply_policy` at `policy.py:48-49` silently returns unchanged `df` when column doesn't exist. Policy recorded as "applied" when it wasn't. |
| 138 | **N/A** | Report file does not exist in BUGS/ directory. |
| 139 | **N/A** | Report file does not exist in BUGS/ directory. |
| 140 | **confirmed** | Code at `pii.py:183` shows `return PIISuggestion("none", 1.0, "no PII signal")`. Hardcoded 1.0 confidence regardless of sample size. |
| 145 | **N/A** | Report file does not exist in BUGS/ directory. |
| 146 | **confirmed** | Code at `ingest.py:170-172` shows token parsing stops at whitespace. `- 42` is split into `"-"` and `"42"`. Confirmed edge case. |
| 149 | **N/A** | Report file does not exist in BUGS/ directory. |
| 152 | **confirmed** | Code at `routes.py:198` (`head = snapshot.df.head(PREVIEW_ROW_LIMIT)`) and `:209` (`df = head.clone()`). Polars `head()` already returns a new DataFrame; the `.clone()` is redundant. |
| 153 | **confirmed** | Code at `ingest.py:91-93` shows `_INSERT_RE` with `[\w.\"`]+` character class — no `[]` for SQL Server bracket identifiers. Matches report. |
| 154 | **confirmed** | Code at `ingest.py:149` shows `if nxt == "x" and i + 3 < n:`. Incomplete hex escapes like `\x4` fall through to literal treatment. Matches report. |
| 155 | **confirmed** | Code at `preflight.py:162-164` shows `if col not in df.columns or col not in qi_names: continue`. Non-QI DP columns are silently skipped without parameter validation. |
| 157 | **N/A** | Report file does not exist in BUGS/ directory. |
| 158 | **confirmed** | Code at `ingest.py:79` shows `null_values=["", "NA", "N/A", "null", "NULL"]`. Empty string treated as NULL. Design choice confirmed in current code. |
| 159 | **confirmed** | Code at `session.py:164-170` matches exactly. `bytearray(session.hmac_key)` creates a mutable copy; the original immutable `bytes` object is not zeroed. Report correctly notes this is a Python limitation. |
| 161 | **confirmed** | Code at `app.js:970-971` shows hardcoded `0.10` threshold: `k.suppression_ratio < 0.10 ? "" : "warn"`. Does not use server-provided cap. |
| 162 | **confirmed** | Code at `pii.py:29-31` shows `EMAIL_RE` with `[A-Za-z0-9._%+\-]+` local part — no support for RFC 5322 quoted local parts. Matches report. |
| 163 | **confirmed** | Code at `app.js:397` shows `const action = tr.querySelector(".action").value;` with no validation against allowed actions. Matches report. |
| 174 | **confirmed** | Duplicate of BUG-154 covering the same hex escape issue at `ingest.py:149-155`. Code confirmed. |
| 175 | **confirmed** | Code at `pii.py:190-191` shows `detect_dataframe` with no `isinstance(df, pl.DataFrame)` guard. Matches report. |
| 177 | **confirmed** | Code at `metrics.py:42-45` shows `edges: [lo] + [float(v) for v in hist["breakpoint"].to_list()]`. Polars `hist(bin_count=N)` returns N+1 breakpoints and N counts, producing N+2 edges for N counts. |
| 179 | **confirmed** | Overlap with BUG-125. Code at `pii.py:92-107` matches. Only 4 regions tested; `region=None` first pass requires `+` prefix. |
| 180 | **confirmed** | Code at `pii.py:33` shows `CREDIT_CARD_RE = re.compile(r"^\d{13,19}$")` and `pii.py:110-112` shows Luhn check without BIN/IIN prefix validation. Matches report. |
| 183 | **confirmed** | Code comparison confirms duplication: `preflight.py:162-192` and `pipeline.py:170-208` have near-identical DP validation. Preflight lacks `is_numeric()` check that pipeline has at line 191. |
| 184 | **N/A** | Report file does not exist in BUGS/ directory. |
| 187 | **confirmed** | Code at `primitives.py:88-110` uses `Decimal(str(v))` for float values. `Decimal(str(0.1 + 0.2))` produces `Decimal('0.30000000000000004')`. `_fmt_decimal` strips trailing zeros but not float artifacts. Matches report. |
| 188 | **N/A** | Report file does not exist in BUGS/ directory. |
| 189 | **confirmed** | Code at `app.js:31-33` shows `$(id).classList.add("active")` without null-checking `$(id)`. If element is missing, TypeError crashes the UI. |
| 190 | **N/A** | Report file does not exist in BUGS/ directory. |
| 194 | **confirmed** | Code at `ingest.py:143-157` shows unrecognized escapes fall through to `buf.append(c)` (appending backslash). `\z` produces literal `\z`. Matches report. |
| 195 | **confirmed** | Code at `metrics.py:38-45` shows `lo = float(clean.min())` prepended to Polars breakpoints. Floating-point rounding can cause `lo` to differ from Polars' actual first bin boundary. |
| 200 | **confirmed** | Code at `app.js:1009-1030` shows `resetToUpload()` does NOT increment `preflightSeq`. An in-flight preflight request can pass the stale-sequence check and render stale data. |
| 201 | **confirmed** | Code at `app.js:219-226` shows `data.session_id`, `data.schema`, `data.pii_suggestions` used without null checks. Only `data.policy_suggestions` has a `|| {}` guard. Matches report. |
| 202 | **confirmed** | Duplicate of BUG-114. Code at `app.js:75-80` confirmed: timer ID from `setTimeout` is never captured or cleared. |

---

## N/A — Report Files Not Found (20 reports)
042, 044, 045, 079, 080, 081, 082, 083, 084, 119, 120, 121, 138, 139, 145, 149, 157, 184, 188, 190

These bug numbers were listed for review but no corresponding `.md` file exists in the BUGS/ directory.
