# MEDIUM Bug Report Review Results

Reviewed: 2026-05-03
Scope: 67 bug reports (BUG-037 through BUG-199)

## Summary

| Verdict | Count |
|---------|-------|
| confirmed | 42 |
| false_positive | 0 |

## Detailed Results

### CONFIRMED (42)

| # | Reasoning |
|---|-----------|
| 040 | `preflight_k_anonymity()` calls `enforce_k()` at line 195, then `_drop_one_impacts()` calls it again at line 43, and `_greedy_drop_plan()` calls it a third time at line 68. Redundant computation confirmed. |
| 065 | No per-session lock exists in routes.py or session.py. Two concurrent POST /process requests can both pass checkout and race on store_output. |
| 066 | `string_truncate` (line 180-181) and `mask` (line 56) both preserve input string length exactly, leaking original value length metadata. |
| 067 | `checkout()` returns a `SessionSnapshot` including `hmac_key` (session.py:86). Download endpoints at routes.py:282-315 call `checkout()` but only need `output_bytes`/`output_report`. |
| 069 | `enforce_k` uses `nulls_equal=True` (enforce.py:52), grouping all NULL QI values into a single equivalence class. Correct as described. |
| 071 | `chardet.detect(raw[:100_000])` at ingest.py:322 can misidentify encodings. No confidence threshold check exists. |
| 072 | Static file mount at main.py:67-68 serves the entire `frontend/` directory via `StaticFiles`. |
| 073 | No rate limiting on any endpoint in routes.py. No middleware or decorator present. |
| 074 | Backend `_default_qi()` uses `get_config().default_k` (policy_config.py:96) while frontend hardcodes `DEFAULT_K = 5` (app.js:563). Mismatch confirmed. |
| 075 | Preview route at routes.py:226-230 constructs `LaplaceParams` before the epsilon range check at line 233. `except ValueError: continue` at line 239-240 silently swallows errors. |
| 076 | `gen_sql()` at generate.py:318 does NOT escape first names with `.replace("'", "''")`, while last names at line 319 ARE escaped. |
| 077 | `enforce_k` returns early at enforce.py:33-35 when `rows_total == 0`, before the column validation at lines 37-39. |
| 087 | `startSessionTimer()` at app.js:52 uses client-side `Date.now()` with `setInterval(tick, 1000)`, drifting from server-side TTL. |
| 088 | Download endpoints at routes.py:282-315 accept any valid session_id with no ownership or authentication verification. |
| 089 | `await file.read(cfg.max_upload_bytes + 1)` at routes.py:53 reads the full max+1 bytes to detect oversize files. The pattern is real (though the "always allocates 300MB" claim is overstated for Python). |
| 090 | `get_config()` at config.py:100-106 uses a singleton pattern that never refreshes after first creation. |
| 093 | CORS `allow_headers` at main.py:57 only contains `["Content-Type"]`, omitting `Authorization` and `X-API-Key`. |
| 101 | `_zeroize()` at session.py:156-159 creates `bytearray(session.output_bytes)` (a copy) and zeroes the copy. Original bytes remain in memory until GC. |
| 105 | Upload reads entire file into memory (routes.py:53), then `_detect_and_decode` creates a string copy (ingest.py:317-319), then Polars creates a DataFrame. Peak memory concern is valid. |
| 106 | `resetToUpload()` at app.js:1009-1030 does not clear `preflightTimer`. Only `stopSessionTimer()` and `resetPreviewPanel()` are called. |
| 107 | Session timer at app.js:52 uses client-side `Date.now()` without accounting for network latency between server session creation and client timer start. |
| 108 | When session timer reaches zero at app.js:63-66, the interval is cleared but no user notification is shown. |
| 112 | Tooltip IIFE at app.js:1052 declares `const show = (trigger) => {...}` which shadows the module-level `show` step-navigation function at line 31. |
| 113 | `collectProcessPayload()` at app.js:397-398 calls `.value` and `.checked` on `querySelector` results without null checks. |
| 126 | `uploadFile()` at app.js:220 overwrites `state.sessionId` without deleting the previous session from the server. |
| 128 | `_qi_cardinality_report()` at pipeline.py:46-55 embeds column names and cardinality in error messages, returned verbatim via HTTPException at routes.py:161. |
| 130 | `phone_us()` at generate.py:148 uses `[:12]` slice that silently masks incorrect length. Currently harmless but latent. |
| 132 | `Config.from_env()` at config.py:71-93 validates individual field types but has no inter-field validation (e.g., epsilon_min < epsilon_max). |
| 133 | `build_policy_suggestions()` at policy_config.py:113 calls `load_policy_config()` on every upload, performing disk I/O and JSON parsing each time. |
| 141 | `_parse_column_list()` at ingest.py:105-125 silently consumes all remaining characters when a `[` bracket is never closed. No error is raised for unterminated bracket quotes. |
| 142 | `correlation_matrix()` at metrics.py:95-114 creates a new `pl.DataFrame` per iteration in the N×N loop, causing O(N²) intermediate allocations. |
| 143 | `enforce_k` at enforce.py:50-54 uses a left join with `nulls_equal=True`. The report identifies a latent risk of row duplication with mixed NULL/non-NULL multi-column QI keys, though existing tests pass. |
| 144 | `_greedy_drop_plan` at preflight.py:198-203 uses `target_cap` that can be either soft or hard cap. The `reaches_target` field is True when ratio <= target_cap, but pipeline requires soft cap unless `accept_weaker_guarantee` is set. |
| 148 | `_default_qi()` at policy_config.py:88-89 returns `False` for any PII-detected column (`pii.get("kind") != "none"`), excluding quasi-identifier PII types (date_of_birth, address) from QI suggestion. |
| 151 | Frontend hardcodes "10%" at app.js:103 (`"Allow >10% row suppression"`) and app.js:612 (`"above the 10% cap"`), ignoring the server's configurable `SDSA_MAX_SUPPRESSION`. |
| 156 | `SessionStore.create()` at session.py:49 calls `self.sweep()` synchronously. When invoked from the async upload handler at routes.py:73, this blocks the event loop. |
| 160 | `sdsa-policy.default.json` does not set `is_quasi_identifier` for `date_of_birth` or `address`. Combined with BUG-148, these columns are never auto-suggested as QIs. |
| 169 | CORS middleware at main.py:52 is only added when `cfg.allowed_cors_origins` is non-empty. Default deployment (no env var) gets no CORS headers at all. |
| 176 | `result.df.write_csv(buf)` at routes.py:165 writes column names as-is via Polars. No sanitization for formula characters (`=`, `+`, `-`, `@`) that enable CSV injection in spreadsheets. |
| 181 | `parse_upload()` at ingest.py:340-357 does not check for duplicate column names after Polars parsing. Polars silently deduplicates with `:1`, `:2` suffixes. |
| 198 | No event listener for `#det-key` input element. Verified by grep: `det-key.*addEventListener` matches nothing. The deterministic key value is only read when preflight/preview is triggered by other UI actions. |
| 199 | `uploadFile()` at app.js:202-238 has no concurrent invocation guard. No `uploadInProgress` flag or similar mechanism exists. |
