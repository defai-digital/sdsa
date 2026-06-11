# SDSA Bug Reports

Updated: 2026-06-07 (round 10)

## Fixed in Earlier Sessions

| Bug | What was fixed |
|-----|----------------|
| BUG-037/171 | `checkout()` clones DataFrame; snapshot no longer shares mutable reference |
| BUG-038/131/164 | Preflight rejects deterministic mode without `SDSA_DEPLOYMENT_SALT` |
| BUG-040 | Eliminated redundant `enforce_k` calls in preflight — pre-computed result passed to `_drop_one_impacts` and `_greedy_drop_plan` |
| BUG-041 | Greedy drop loop guarded with `len(current_qis) > 1` — prevents vacuous "success" when all QI columns are dropped |
| BUG-043 | SQL `_parse_value` raises `ParseError` for unrecognized tokens instead of silently returning raw strings |
| BUG-046 | CORS `allow_headers` now includes `Authorization` and `X-API-Key` |
| BUG-049 | `date_truncate` error message no longer includes raw PII value |
| BUG-052/138 | PII detection uses random sample instead of `head()` |
| BUG-053/091 | Duplicate QI column names deduplicated before `enforce_k` |
| BUG-056 | `_detect_and_decode` catches `LookupError` for unsupported chardet encodings |
| BUG-057 | SQL assembler error message no longer leaks raw Polars error text |
| BUG-058/134 | `renderReview` null-guards `report.k_anonymity`, `report.privacy`, `claim-box` |
| BUG-059 | `readErrorMessage` handles Pydantic 422 array `detail` format |
| BUG-063 | `ProcessRequest.policies` limited to 500 entries |
| BUG-065 | Concurrent `POST /process/{session_id}` returns 409 — per-session lock via `_processing_sessions` set |
| BUG-068 | Column names validated for max length (200) and null bytes |
| BUG-070/165 | Preflight derives deterministic HMAC key same way as pipeline |
| BUG-074 | Frontend reads `default_k` from server `UploadResponse` instead of hardcoded 5 |
| BUG-075 | Preview raises HTTP 400 for out-of-range epsilon; check moved before `LaplaceParams` construction |
| BUG-203 | `render_markdown` applies `_md_escape()` to `deterministic_key_name` |
| BUG-204 | `Config.from_env()` raises `ConfigError` if `SDSA_DEFAULT_K < 2` |
| BUG-205 | `Config.from_env()` raises `ConfigError` if `epsilon_min >= epsilon_max` |
| BUG-206 | `Config.from_env()` raises `ConfigError` if `max_suppression >= hard_max_suppression` |
| BUG-208 | Frontend error messages use `preflight.suppression_cap` instead of hardcoded "10%" |
| BUG-209 | `build_validation` samples up to 10 000 rows before running `correlation_matrix` |
| BUG-076/085 | SQL/CSV sample generators escape apostrophes in names |
| BUG-077 | `enforce_k` validates QI columns before short-circuiting on empty DataFrames |
| BUG-078 | `MemoryError` re-raised from CSV/TXT parser broad `except Exception` blocks |
| BUG-079 | Session TTL uses `??` instead of `||` for nullish coalescing |
| BUG-080 | `esc()` escapes backticks |
| BUG-081/121 | Removed unused `schema` dict in SQL parser |
| BUG-082 | Removed redundant `import math` inside `correlation_matrix` |
| BUG-084 | Removed unused `detect_encoding()` function |
| BUG-087/107 | Session timer uses server-provided `session_expires_at` timestamp — eliminates client-clock drift |
| BUG-099/172 | `render_markdown` escapes markdown special characters in column names |
| BUG-100/192 | `string_truncate` masks at least one character even for short values |
| BUG-102 | `_sweep_loop` shutdown catches all exceptions |
| BUG-103 | `apply_laplace` wraps `math.isfinite` in try/except |
| BUG-104 | `clear_output()` return value checked; 404 raised if expired |
| BUG-106/200 | `resetToUpload()` clears `preflightTimer` and resets `preflightSeq` |
| BUG-108 | Session timer shows error notification on expiration |
| BUG-110/166 | `renderPreviewSanitized` bounds-checks `san[i][j]` |
| BUG-111 | `buildParams` wraps `JSON.parse` in try/catch |
| BUG-116 | `resetPreviewPanel()` resets `previewSeq` |
| BUG-123 | `date_truncate` raises `ValueError` for `pl.Time` columns |
| BUG-124 | `mask` raises `ValueError` when `mask_char` is empty |
| BUG-126 | `uploadFile()` DELETEs previous session before new upload |
| BUG-135 | Frontend validates k input (NaN → 5, clamped [2, 1000]) |
| BUG-139 | `_categorical_stats` excludes nulls from cardinality |
| BUG-141 | SQL parser raises `ParseError` for unterminated bracket quotes |
| BUG-145/192 | `string_truncate` validates `pad_char` is single char |
| BUG-149 | DELETE session returns 404 for non-existent sessions |
| BUG-170 | `numeric_bin` returns `None` for non-finite values |
| BUG-173/185 | `deterministic_key_name` limited to [1, 256] chars |
| BUG-193 | Preview endpoint uses consistent deterministic key derivation |
| BUG-196 | `col.kind` escaped via `esc()` |
| BUG-197 | DP bound inputs use `esc(String(...))` |
| BUG-198 | `det-key` input has debounced listener for preflight/preview |
| BUG-215 | Preflight `qi_columns` deduplicated with `dict.fromkeys()` — matches pipeline |
| BUG-216 | `renderPreflight` innerHTML uses `esc()` on summary and meta strings |
| BUG-217 | Preflight reuses `_derive_deterministic_key` from pipeline — single source of truth |
| BUG-219 | SQL parser rejects hex literals longer than 16 digits (64-bit max) |
| BUG-220 | Process endpoint `clear_output` changed to best-effort — eliminates TOCTOU |
| BUG-221 | Preflight validates numeric dtype before `apply_laplace` — prevents PII leak in errors |
| BUG-222 | Preview endpoint enforces deterministic+DP exclusion (ADR-0008) |
| BUG-223 | `PreflightRequest.deterministic_key_name` constrained to [1, 256] chars |
| BUG-224 | `_md_escape` escapes `<` and `>` — prevents HTML injection in markdown reports |
| BUG-225 | `showError`/`flashDropzoneError` store timer IDs and clear previous timers |
| BUG-226 | Step-click listeners use event delegation — prevents duplicate listeners if step bar is re-rendered |

## False Positives (Closed — Not Bugs)

| Bug | Reason |
|-----|--------|
| BUG-069 | `nulls_equal=True` in `enforce_k` is intentional — NULL QI values form their own equivalence class, which is correct k-anon semantics and documented in the code |
| BUG-089 | `file.read(max_upload_bytes + 1)` does not pre-allocate a fixed buffer; Python's async `UploadFile.read(n)` reads up to n bytes from the stream — the +1 is a correct oversize-detection idiom |
| BUG-207 | `_zeroize` bytearray zeroing is best-effort and already documented in ADR-0007; Python `bytes` are immutable and cannot be zeroed in place — this is a known language limitation, not a fixable code defect |
| BUG-210 | Fixed `seed=0` in `_sample_strings` is intentional — documented in-code as ensuring deterministic detection across re-runs on the same data |
| BUG-211 | All current `ValueError`s from primitives are genuine param-validation errors; `PolicyApplicationError` is re-raised before the broad catch — hypothetical future concern, not a present bug |
| BUG-212 | Per-call DP accounting is a deliberate architectural decision; report's own suggested fix is "document it" — not a code defect |
| BUG-213 | `hist(bin_count=N)` returns N rows (upper-bound breakpoints only); prepending `lo` correctly produces N+1 edges for N bins — standard histogram representation |
| BUG-214 | `<` and `>` are already escaped by `esc()`, preventing the tag-injection attack vector; escaping `/` is redundant in this context |
