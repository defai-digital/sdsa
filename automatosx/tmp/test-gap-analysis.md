# SDSA Test Gap Analysis

Generated: 2026-04-13
Scope: all 10 test files in `backend/tests/` vs. all source modules in `backend/src/sdsa/`

---

## CATEGORY 1: Potentially Buggy Test Assertions

### BUG-1: Logical error in `test_dp.py:111` — `or` vs `and`
**File:** `backend/tests/test_dp.py`, line 111
```python
assert "nan" not in serialized.lower() or "Infinity" not in serialized
```
**Problem:** Due to Python operator precedence, this evaluates as:
`("nan" not in serialized.lower()) or ("Infinity" not in serialized)`

This **passes** even if "nan" is present, as long as "Infinity" is absent. A serialized string containing `{"x": NaN}` (lowercase) would pass this check, which is the exact scenario the test is meant to prevent. The line above (110) catches uppercase "NaN", but this line is meant to catch the lowercase variant that might slip through.

**Fix:** Change `or` to `and`:
```python
assert "nan" not in serialized.lower() and "Infinity" not in serialized
```

### BUG-2: Misleading test name `test_kanon.py:21` — name says k=1, code uses k=2
**File:** `backend/tests/test_kanon.py`, line 21–25
```python
def test_k_of_1_equivalent_to_no_suppression():
    df = pl.DataFrame({"a": [1, 2, 3], "b": [1, 2, 3]})
    res = enforce_k(df, qi_columns=["a"], k=2)
    assert res.df.height == 0
```
**Problem:** The test name claims k=1, but the code uses k=2. The real scenario being tested is "all unique values at k≥2 → all suppressed". There is no test for the actual k=1 case. Since the source code at `enforce.py:30` raises `ValueError` for k < 2, the test name is misleading — it suggests k=1 should work like "no suppression" but the source forbids it.

### BUG-3: Probabilistic assertion in `test_pipeline.py:55`
**File:** `backend/tests/test_pipeline.py`, line 55
```python
assert any(abs(v - int(v)) > 0 for v in after)
```
**Problem:** This asserts that at least one DP-noised salary has a fractional part. With scale=60000 this is extremely likely, but the test is **probabilistic**, not deterministic. On rare RNG outcomes (or if the clamping range is tight), all noised values could land on integers by coincidence. The test is not truly flaky at current parameters, but it's fragile — changing bounds or epsilon could cause intermittent failures.

---

## CATEGORY 2: Untested Edge Cases Per Module

### 2.1 Ingest (`test_ingest.py` ↔ `src/sdsa/ingest.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **CSV with header-only (no data rows)** | `ingest.py:61` — `if df.height == 0: raise ParseError` | `b"a,b\n"` would be rejected with ParseError, but this is not tested. Only empty-bytes (`b""`) is tested. |
| **CSV with inconsistent column counts** | `ingest.py:53` — Polars may error or silently produce nulls | No test for `"a,b\n1,2,3\n4"`. Behavior depends on Polars version. |
| **SQL row width mismatch** | `ingest.py:248-253` — explicitly checks `len(r) != len(columns)` | Source raises ParseError for wrong-value-count rows, but no test exercises this path. |
| **SQL boolean values (TRUE/FALSE)** | `ingest.py:167-168` — parses TRUE/FALSE | Not tested. |
| **SQL negative numbers** | `ingest.py:175-177` | Not tested. SQL like `VALUES (-5)` should parse. |
| **SQL scientific notation** | `ingest.py:175-176` — checks for `.eE` in token | `VALUES (1.5e10)` not tested. |
| **TXT fallback to comma delimiter** | `ingest.py:77` — default best=`,` | Text with no consistent delimiter should fall back to comma, untested. |
| **UTF-8 BOM detection** | `ingest.py:33-34`, `ingest.py:301-302` | `detect_encoding` handles BOM for both standalone and `_detect_and_decode`, but neither path is tested. |
| **Non-UTF-8 encoding fallback** | `ingest.py:306-314` | `_detect_and_decode` tries chardet on UnicodeDecodeError, but no test provides actual non-UTF-8 bytes (e.g., windows-1252 encoded file). |
| **SQL mixed-case keywords** | `ingest.py:109` — `re.IGNORECASE` | No test for `insert into` (lowercase) or `Insert Into` (mixed case). |
| **SQL with double-quoted identifiers** | `ingest.py:108` — regex includes `\"` | Not tested. |
| **SQL with no column list** | `ingest.py:237-238` — generates `col_N` names | Not tested: `INSERT INTO t VALUES (1, 'x');` |

### 2.2 Anonymize Primitives (`test_anonymize.py` ↔ `src/sdsa/anonymize/primitives.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **mask with empty string** | `primitives.py:34-35` — `if n == 0: return s` | Empty string input should pass through unchanged, untested. |
| **mask with None values** | `primitives.py:30-31` — `if v is None: return None` | Implicitly tested via Polars but no explicit assertion. |
| **mask with keep_prefix=0, keep_suffix=0** | `primitives.py:52` | Full mask, no prefix/suffix retained. Not tested. |
| **mask with custom mask_char** | `primitives.py:18` — `mask_char="*"` | Not tested with e.g. `mask_char="X"`. |
| **hmac_hash with None values** | `primitives.py:59-60` | Not explicitly tested. |
| **hmac_hash with empty string** | `primitives.py:62` | Should produce a valid hash of `""`, not tested. |
| **tokenize with None values** | `primitives.py:70-71` | Not explicitly tested. |
| **numeric_bin with None values** | `primitives.py:89-90` | Not tested. |
| **numeric_bin with negative bin_width** | `primitives.py:86-87` — raises ValueError | Not tested. Source raises, but only mask negative params are tested. |
| **numeric_bin with zero bin_width** | `primitives.py:86` — `bin_width <= 0` | Not tested. |
| **date_truncate with "day" granularity** | `primitives.py:111,136` | Only "year" and "month" are tested. "day" is a valid option. |
| **date_truncate with None values** | `primitives.py:118` | Not tested. |
| **date_truncate with Datetime objects** | `primitives.py:110` | Only Date objects are tested. Datetime columns (with time component) are untested. |
| **date_truncate with invalid granularity** | `primitives.py:107-108` | `granularity="week"` should raise ValueError, untested. |
| **string_truncate with keep=0** | `primitives.py:140-149` | Full masking, untested. |
| **string_truncate with None values** | `primitives.py:143-144` | Not tested. |
| **string_truncate with string shorter than keep** | `primitives.py:146-147` | `string_truncate("hi", keep=5)` should return `"hi"`, untested. |
| **redact with custom replacement** | `primitives.py:77` — `replacement="[REDACTED]"` | Not tested with custom string. |
| **redact with all-None series** | `primitives.py:78` | Not tested. |

### 2.3 DP (`test_dp.py` ↔ `src/sdsa/dp/`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **LaplaceParams with negative epsilon** | `laplace.py:69` — `epsilon <= 0` | Only epsilon=0 tested. Negative epsilon should also raise. |
| **apply_laplace with all-None series** | `laplace.py:76-77` | Not tested. |
| **apply_laplace with mixed None and numeric** | `laplace.py:76-77` | Not tested. Should preserve None. |
| **apply_laplace with negative input values** | `laplace.py:79` — clamping | Not tested. Negative values within bounds should be preserved. |
| **accountant.charge with epsilon=0** | `accountant.py:17-18` — raises ValueError | Not tested. |
| **accountant.charge with negative epsilon** | `accountant.py:17-18` | Not tested. |
| **accountant.max_epsilon() with no charges** | `accountant.py:22` — `default=0.0` | Not tested. |
| **correlation_matrix with empty DataFrame** | `metrics.py:85-86` | Should return `{}`, untested. |
| **correlation_matrix with single numeric column** | `metrics.py:87-102` | Should return `{"col": {"col": 1.0}}`, untested. |
| **correlation_matrix with no numeric columns** | `metrics.py:85` | Should return `{}`, untested. |
| **correlation_matrix with all-constant numeric columns** | Already tested (BUG-1 assertion issue) | Only partially covered due to assertion bug. |

### 2.4 K-Anonymity (`test_kanon.py` ↔ `src/sdsa/kanon/enforce.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **k < 2 rejection** | `enforce.py:30-31` — `raise ValueError("k must be >= 2")` | Not tested. k=1, k=0, k=-1 should all raise. |
| **Empty DataFrame** | `enforce.py:33` — returns immediately | Not tested. |
| **Single-row DataFrame** | `enforce.py:33` | Not tested. At k≥2, single row should be suppressed. |
| **All rows in one class (no suppression)** | `enforce.py:50-56` | Not tested: `enforce_k(df, qi=["dept"], k=3)` where all rows share same dept. |
| **Missing QI columns** | `enforce.py:37-39` — raises ValueError | Not tested: requesting a QI column that doesn't exist in the DataFrame. |
| **Multiple QI columns with varying class sizes** | `enforce.py:50` | Only 1-2 QI columns tested. No test with 3+ QI columns where classes have different sizes. |
| **QI columns with empty string values** | `enforce.py:50-56` | Empty strings group together, untested. |
| **QI columns with mixed empty and null** | `enforce.py:52` — `nulls_equal=True` | Empty string `""` and `None` form different groups. Untested and potentially surprising. |

### 2.5 Pipeline (`test_pipeline.py` ↔ `src/sdsa/pipeline.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **"drop" action** | `policy.py:48-49` — drops the column | Never tested in pipeline. Column should be absent from output. |
| **"tokenize" action** | `policy.py:56-57` | Never tested in pipeline context. |
| **"redact" action** | `policy.py:58-59` | Never tested in pipeline context. |
| **"mask" action with parameters** | `policy.py:51-53` | Never tested in pipeline. Only tested in isolation. |
| **Multiple DP columns** | `pipeline.py:166-205` | Only single DP column tested. Behavior with 2+ DP columns is untested. |
| **No QI columns + no suppression** | `pipeline.py:208-210` | Empty QI list should mean no k-anon enforcement, untested in pipeline. |
| **Column referenced in policy but missing from DataFrame** | `policy.py:39-40` — silently returns df | Untested. A policy for "nonexistent_col" should be silently ignored. |
| **Report structure without DP** | `pipeline.py:245-254` | No test verifies report fields like `privacy.max_epsilon == 0` when no DP is used. |
| **Report structure with deterministic mode** | `pipeline.py:253` | No test checks that `report["deterministic_mode"]` is populated when deterministic_key_name is set. |
| **Validation metrics** | `pipeline.py:232` | No test examines `report["validation"]` contents. |
| **DP on non-QI column** | `pipeline.py:136-137` | dp_laplace on a non-QI column should still work (noise is added, but it's not used for k-anon grouping). Untested. |

### 2.6 API Routes (`test_api.py` ↔ `src/sdsa/api/routes.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **Upload too-large file (413)** | `routes.py:45-46` | No test sends a file exceeding max_upload_bytes. |
| **Process with non-existent session (404)** | `routes.py:112-113` | Not tested. |
| **Download before processing (404)** | `routes.py:170-171` | Not tested explicitly (only tested after deletion). |
| **Preflight with non-existent session (404)** | `routes.py:152-153` | Not tested. |
| **Delete non-existent session** | `routes.py:198` | Not tested. Should it return 200/404? |
| **Upload .sql file through API** | `routes.py:41-91` | Only .csv tested through the API. .sql and .txt extensions are supported by parse_upload but untested via HTTP. |
| **Upload with no filename** | `routes.py:49` — `file.filename or ""` | Edge case: what if the upload has no filename? Should use empty string, triggers ParseError for unsupported extension. |
| **Process with malformed JSON body** | `routes.py:109` | FastAPI handles this, but no test verifies the error shape. |
| **Content-Disposition header on downloads** | `routes.py:172,192` | Not verified in any test. Should contain session_id. |
| **Successful reprocess (overwrite previous output)** | `routes.py:117-119` | Failed reprocess is tested (test_failed_reprocess_clears_previous_downloads), but successful reprocess replacing previous output is not. |
| **CORS with multiple origins** | `config.py:47` — `_parse_csv_list` | Only single-origin CORS tested. Comma-separated origins untested. |
| **Malformed process request (missing k)** | `routes.py:109` | Pydantic defaults k=5, but what about invalid types for k (e.g., string)? |

### 2.7 PII Detection (`test_detect.py` ↔ `src/sdsa/detect/pii.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **government_id detection** | `pii.py:44` — SSN, NRIC, etc. | No test for SSN column name hint or SSN values. |
| **name detection** | `pii.py:39-40` | No test for column named "first_name" or "fullname". |
| **address detection by content** | `pii.py:41-42` | Only column-name hint tested (test_mailing_address_does_not_hit_email_hint). No content-based address detection. |
| **date_of_birth detection** | `pii.py:45-46` | No test for column named "dob" or "birth_date" with date-like values. |
| **identifier detection by high cardinality** | `pii.py:160-164` | Requires >20 rows with >95% unique. Not tested. |
| **Partial email match ratio** | `pii.py:147` — threshold 0.80 | A column with 50% emails should NOT be detected. Not tested. |
| **Partial phone match ratio** | `pii.py:151` — threshold 0.70 | Not tested. |
| **Empty DataFrame detection** | `pii.py:130-132` | Not tested. |
| **Numeric series with email-hint column name** | `pii.py:130-132` | If column is named "Email" but has numeric dtype, behavior is untested. |
| **Column named "id" or "uuid"** | `pii.py:48` — identifier hint | Not tested. |
| **Column named "ssn"** | `pii.py:44` | Not tested. |

### 2.8 Schema Inference (`test_detect.py:45-50` ↔ `src/sdsa/detect/schema.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **Boolean column inference** | `schema.py:16-17` | Not tested. |
| **Datetime column inference** | `schema.py:20-21` | Not tested (only inferred indirectly in test_parse_upload_csv_parses_iso_dates). |
| **Null-only column** | `schema.py:24-25` | Should return "string", untested. |
| **Empty DataFrame** | `schema.py:32-33` | Should return [], untested. |
| **Categorical vs string boundary** | `schema.py:27-28` | 5% cardinality ratio threshold not tested at boundary. |
| **min/max for numeric with all-null** | `schema.py:46-47` | Should be None, untested. |

### 2.9 Policy Config (`test_policy_config.py` ↔ `src/sdsa/policy_config.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **Empty schema** | `policy_config.py:115` | Not tested. Should return `{}`. |
| **dp_laplace suggestion without min/max in schema** | `policy_config.py:141-144` | The `setdefault` calls should leave epsilon with default but no bounds. Not tested. |
| **Case-insensitive field lookup** | `policy_config.py:102-106` | `_field_lookup` lowercases both names for comparison, but not tested. |
| **Merge behavior** | `policy_config.py:64-71` | `_merge_dicts` deep-merges nested dicts. Not tested independently. |
| **Invalid JSON structure (not a dict)** | `policy_config.py:59-60` | Not tested. Should raise PolicyConfigError. |
| **Missing default policy file** | `policy_config.py:77-78` | If sdsa-policy.default.json doesn't exist, behavior is untested. |
| **by_kind fallback** | `policy_config.py:128-130` | Fallback from PII kind to column kind not tested (all tests either match field or pii_kind). |

### 2.10 Preflight (`test_preflight.py` ↔ `src/sdsa/preflight.py`)

| Gap | Source Line | Risk |
|-----|-------------|------|
| **Empty DataFrame** | `preflight.py:122-123` | Not tested. |
| **No QI columns** | `preflight.py:136` | `qi_names` would be empty, no transforms applied, untested. |
| **Single QI column (drop_one returns [])** | `preflight.py:39` — `if len(qi_columns) <= 1: return []` | Not tested. |
| **Already within target cap (greedy returns None)** | `preflight.py:67-68` | Not tested. |
| **DP on QI column that succeeds** | `preflight.py:143-173` | Only DP rejection cases tested. No test where DP params are valid and epsilon is in range. |
| **Suggestions string content** | `preflight.py:186-231` | No test verifies the content of the `suggestions` list. |
| **Empty policies list** | `preflight.py:138` | Not tested. |

---

## CATEGORY 3: Untested Feature Combinations

### COMBO-1: DP + QI column
`pipeline.py:166-205` — DP noise applied to a column that is also a QI. The noise changes QI values, potentially creating new small equivalence classes or breaking existing ones. This interaction is **never tested**. The preflight skips non-QI DP but the pipeline does NOT skip QI DP.

### COMBO-2: hash + deterministic mode + multiple sessions
`test_pipeline.py:176-201` tests this for 2 sessions but only with 1 column. What about 3+ columns with mixed actions (some hash, some tokenize) in deterministic mode?

### COMBO-3: string_truncate on QI + numeric_bin on QI
Two QI columns with different generalization strategies. Not tested in pipeline or preflight.

### COMBO-4: drop action on a QI column
`policy.py:48-49` drops the column, but `pipeline.py:208-210` still lists it as a QI. This would cause `enforce_k` to fail with "QI columns not in dataframe". This is a **potential bug** — the pipeline should either skip dropped QI columns or reject the configuration.

### COMBO-5: date_truncate on a column parsed as Date vs. string
The `test_api.py:186-225` tests date_truncate on a datetime column parsed by Polars. But `test_anonymize.py:106-111` tests non-ISO strings. There is no test where a column is auto-parsed as Date by Polars and then date_truncate is applied with "year" granularity through the pipeline.

### COMBO-6: multiple policy files (default + configured)
The merge behavior between `sdsa-policy.default.json` and a user-provided `sdsa-policy.json` is tested in `test_api.py:160-183` but only for field-level overrides. Deep merge behavior (e.g., partial defaults override) is untested.

---

## CATEGORY 4: Missing Tests for Reported Regression Fixes

Several tests document regression fixes. These are valuable but the **original bug condition** often lacks a complementary test for the "before fix" state:

| Regression Test | What's Still Missing |
|-----------------|---------------------|
| `test_mask_enforces_at_least_one_char_masked_on_short_values` | No test for `keep_prefix + keep_suffix == len(s) - 1` (exactly at boundary, 1 char masked) |
| `test_laplace_sampler_handles_boundary_rng_outputs` | No test for `randbits` returning `1 << 53` (max value, p very close to 1) |
| `test_null_qi_rows_are_not_silently_dropped` | No test for mixed null + non-null values in QI column |
| `test_correlation_matrix_returns_none_for_constant_columns` | Assertion bug (BUG-1) means this test doesn't fully validate |
| `test_date_truncate_parses_non_iso_strings` | No test for ISO format strings that the function should handle natively |
| `test_user_column_named_cls_size_does_not_collide` | No test for BOTH `_cls_size` AND `_sdsa_cls_size` in the same DataFrame |
| `test_preflight_skips_non_qi_transforms` | No test verifying QI transforms ARE applied (the inverse case) |
| `test_failed_reprocess_clears_previous_downloads` | No test for successful reprocess (COMBO-7 above) |

---

## CATEGORY 5: Security-Sensitive Untested Paths

### SEC-1: HMAC key zeroization on session expiry
`core/session.py:81-101` — `_zeroize` attempts to overwrite key bytes in memory. `test_core.py:11-22` tests that references are nulled, but **does not verify that the bytearray was overwritten** (Python makes this hard, but the attempt should at least not crash).

### SEC-2: Session store thread safety under concurrent get/delete
`core/session.py:46-64` — `get()` and `delete()` both acquire the lock, but `test_core.py` only tests `create()` under concurrency. Concurrent `get` + `delete` of the same session is untested.

### SEC-3: Config singleton reset between tests
`test_api.py` and `test_core.py` both set `config_module._config = None` in finally blocks. If any test fails before the finally, the global config could be corrupted for subsequent tests. This is a test isolation issue, not a code bug.

### SEC-4: Deployment salt behavior
`config.py:32-36` — If `SDSA_DEPLOYMENT_SALT` is not set, a random salt is generated. This means deterministic mode produces different hashes across restarts when no salt is configured. This behavior is **not tested or documented in tests**.

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Potentially buggy assertions | 3 |
| Untested edge cases (per module) | ~85 |
| Untested feature combinations | 7 |
| Missing regression complements | 8 |
| Security-sensitive untested paths | 4 |
| **Total findings** | **~107** |

### Priority Recommendations

**P0 (Fix Now):**
1. BUG-1: Fix `or` → `and` in `test_dp.py:111`
2. COMBO-4: Investigate and test `drop` action on QI column — potential runtime error
3. COMBO-1: Test DP noise on a QI column — correctness of k-anonymity after noise

**P1 (High Value):**
4. Add tests for k < 2 rejection in enforce_k
5. Add test for upload file size limit (413)
6. Add tests for session not found (404) on process/preflight/download
7. Add test for "drop" and "tokenize" actions in pipeline
8. Add test for date_truncate with "day" granularity
9. Add test for correlation_matrix with empty DataFrame

**P2 (Coverage Improvement):**
10. Add .sql and .txt upload tests through the API
11. Add government_id and name PII detection tests
12. Add boolean and datetime schema inference tests
13. Add concurrent get/delete session tests
14. Test report structure fields (validation, privacy, deterministic_mode)
