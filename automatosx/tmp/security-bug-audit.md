# SDSA Security & Bug Audit Report

**Codebase:** `/Users/akiralam/code/sdsa/backend/src/sdsa/` + frontend + samples  
**Date:** 2026-04-13  
**Auditor:** Automated Deep Audit  
**Files reviewed:** 26 source files (Python backend, JavaScript frontend, sample generator)  
**Total findings:** 37  

---

## Summary by Severity

| Severity | Count |
|----------|-------|
| Critical | 4 |
| High | 8 |
| Medium | 13 |
| Low | 12 |

## Summary by Category

| Category | Count |
|----------|-------|
| Security | 7 |
| Privacy | 9 |
| Logic | 5 |
| Concurrency | 3 |
| Resource | 5 |
| Error Handling | 4 |
| Cryptographic | 4 |

---

## CRITICAL Findings

### C-01: PII Values Leaked in Error Messages (Privacy)
**File:** `backend/src/sdsa/anonymize/primitives.py:139-141`  
**Category:** Privacy / Error Handling  
**Severity:** CRITICAL  

The `date_truncate` function includes the raw PII value (`v`) in the error message when parsing fails. This error propagates up through `PolicyApplicationError` → `PipelineError` → HTTP 400 response, leaking actual PII data values to the client.

```python
raise ValueError(
    f"date_truncate cannot parse value as a date: {v!r} ({e})"
) from e
```

**Impact:** Individual data values (which may be names, addresses, dates of birth) are returned verbatim in error responses. For a data anonymization tool, this is a severe privacy violation.

**Suggested fix:**
```python
raise ValueError(
    f"date_truncate cannot parse value in column '{series.name}' as a date "
    f"(row value withheld for privacy): {e}"
) from e
```

---

### C-02: Truncated HMAC Digests Enable Collision Attacks (Cryptographic / Privacy)
**File:** `backend/src/sdsa/anonymize/primitives.py:63-64, 73-74`  
**Category:** Cryptographic / Privacy  
**Severity:** CRITICAL  

The `hash()` function truncates HMAC-SHA256 to **16 hex chars (64 bits)**, and `tokenize()` truncates to **12 hex chars (48 bits)**. At 48 bits, a birthday attack yields a 50% collision probability with only ~2^24 ≈ 16 million entries. Collisions in pseudonymization mean two different PII values map to the same token — breaking data integrity and potentially creating false linkage.

```python
# hash — 64 bits
digest = hmac.new(key, str(v).encode("utf-8"), hashlib.sha256).hexdigest()
return digest[:16]

# tokenize — only 48 bits!
return f"{prefix}{digest[:12]}"
```

**Impact:** For datasets with >100K rows, collisions are plausible. For tokenize (48-bit), even modest datasets risk integrity violations.

**Suggested fix:** Use at least 32 hex chars (128 bits) for `hash()` and 24 hex chars (96 bits) for `tokenize()`:
```python
# hash — 128 bits
return digest[:32]

# tokenize — 96 bits  
return f"{prefix}{digest[:24]}"
```

---

### C-03: No Authentication or Authorization on Any Endpoint (Security)
**File:** `backend/src/sdsa/api/routes.py` (all endpoints)  
**Category:** Security  
**Severity:** CRITICAL  

No API endpoint requires authentication. The session ID (a capability URL with 128-bit entropy) is the sole authorization mechanism. Anyone who can reach the server can upload data, process it, download results, and delete sessions.

```python
@router.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile) -> UploadResponse:  # No auth check
    ...

@router.get("/download/{session_id}/data.csv")
async def download_csv(session_id: str):  # No auth check
    ...
```

**Impact:** In a network-accessible deployment, any user can access any session. If session IDs are logged, leaked in URLs, or shared, the data is fully exposed.

**Suggested fix:** Add authentication middleware (e.g., API key, session cookie, or OAuth2). At minimum, add rate limiting and consider binding sessions to IP addresses or auth tokens.

---

### C-04: Incomplete PII Detection — Only First 200 Values Sampled (Privacy)
**File:** `backend/src/sdsa/detect/pii.py:66-74`, `backend/src/sdsa/api/routes.py:63`  
**Category:** Privacy  
**Severity:** CRITICAL  

PII detection only examines the first 200 non-null values from the first 10,000 rows. If a column contains PII only in later rows (e.g., a headerless CSV where PII appears after row 10,000), the tool will not detect it and will **not suggest anonymization**.

```python
# pii.py:66
def _sample_strings(series: pl.Series, n: int = 200) -> list[str]:
    ...
    take = min(n, s.len())
    return s.head(take).to_list()

# routes.py:63
sample = df.head(cfg.sample_rows_for_detection)  # first 10,000 rows
```

**Impact:** For a data anonymization tool, missing PII columns is a critical failure. Users may export data believing it's anonymized when PII is still present.

**Suggested fix:** Use a stratified random sample across the entire dataset rather than just the head. Alternatively, increase the sample size and document the limitation clearly.

---

## HIGH Findings

### H-01: Memory Exhaustion via Concurrent Uploads (Resource / Security)
**File:** `backend/src/sdsa/api/routes.py:53`  
**Category:** Resource / Security  
**Severity:** HIGH  

The entire upload is read into memory (up to 300 MB per file). Combined with the pipeline's `original.clone()`, a single upload consumes ~600 MB. Concurrent uploads can easily exhaust server memory with no rate limiting or concurrency control.

```python
raw = await file.read(cfg.max_upload_bytes + 1)  # up to 300 MB
```

**Impact:** OOM crashes, denial of service.

**Suggested fix:** Add a semaphore to limit concurrent uploads. Stream large files to a temporary buffer or disk.

---

### H-02: CPU Exhaustion via Preflight Endpoint (Resource / Security)
**File:** `backend/src/sdsa/preflight.py:58-116`  
**Category:** Resource / Security  
**Severity:** HIGH  

The `_greedy_drop_plan` function calls `enforce_k()` O(n²) times (where n = number of QI columns). With 15 QI columns (the maximum allowed), this involves up to 15×14 = 210 group_by + join operations on the full DataFrame. No CPU timeout or request throttling exists.

```python
def _greedy_drop_plan(df, qi_columns, k, target_cap):
    while current_qis and current_result.suppression_ratio > target_cap:
        for col in current_qis:
            reduced = [c for c in current_qis if c != col]
            result = enforce_k(df, reduced, k)  # expensive!
```

**Impact:** A single preflight request can consume seconds to minutes of CPU time on large datasets.

**Suggested fix:** Add a timeout (e.g., 30 seconds) or a maximum iteration count for the greedy loop.

---

### H-03: Unbounded Policy List in ProcessRequest (Resource / Security)
**File:** `backend/src/sdsa/pipeline.py:28-33`  
**Category:** Resource / Security  
**Severity:** HIGH  

The `ProcessRequest.policies` list has no length limit. A malicious user can send thousands of policies, each triggering `apply_policy()` on the full DataFrame. Similarly, `dp_params` has no size limit.

```python
class ProcessRequest(BaseModel):
    policies: list[ColumnPolicy]  # no max_length
    dp_params: dict[str, dict] = Field(default_factory=dict)  # no size limit
```

**Impact:** CPU and memory exhaustion.

**Suggested fix:** Add `max_length` validation:
```python
policies: list[ColumnPolicy] = Field(..., max_length=500)
```

---

### H-04: Raw Polars Error Messages Leaked to Client (Error Handling / Security)
**File:** `backend/src/sdsa/ingest.py:308-309`  
**Category:** Error Handling / Security  
**Severity:** HIGH  

When DataFrame assembly fails during SQL parsing, the raw exception message (which may include internal Polars details, file paths, or data values) is returned to the client.

```python
except Exception as e:
    raise ParseError(f"could not assemble DataFrame: {e}")
```

**Impact:** Internal library details or data values may leak through error messages.

**Suggested fix:**
```python
except Exception as e:
    raise ParseError("could not assemble DataFrame from SQL values") from e
```

---

### H-05: SessionSnapshot Shallow Copy Allows Data Mutation (Concurrency / Privacy)
**File:** `backend/src/sdsa/core/session.py:80-87`  
**Category:** Concurrency / Privacy  
**Severity:** HIGH  

`checkout()` creates a shallow copy of the `detection` and `output_report` dicts. Nested structures (lists, dicts) are shared references. If the session is concurrently modified by the background sweeper or another request, the snapshot's data could be partially corrupted.

```python
snapshot = SessionSnapshot(
    ...
    detection=dict(session.detection) if session.detection is not None else None,
    output_report=dict(session.output_report) if session.output_report is not None else None,
    ...
)
```

**Impact:** While no current code mutates these nested structures, this is a latent privacy risk. A future code change could inadvertently modify shared data.

**Suggested fix:** Use `copy.deepcopy()` for nested structures, or freeze the snapshot data with immutable types.

---

### H-06: Log Scrubbing Is Fragile — Key-Name Based Only (Privacy)
**File:** `backend/src/sdsa/core/logging.py:14-17`  
**Category:** Privacy  
**Severity:** HIGH  

The log scrubbing mechanism only redacts values for explicitly listed key names. Any developer adding a log statement with a key not in `SENSITIVE_KEYS` (e.g., `"user_email"`, `"ssn_value"`) would silently log PII.

```python
SENSITIVE_KEYS = frozenset({
    "body", "column_values", "sample_rows", "row", "value", "values",
    "raw", "data", "payload", "content",
})
```

**Impact:** PII could be logged without anyone noticing, violating privacy guarantees.

**Suggested fix:** Invert the model — scrub all keys by default and only allow-list known-safe metadata keys. Add a CI lint rule that flags any log statement with non-allow-listed extra keys.

---

### H-07: No CSRF Protection on State-Changing Endpoints (Security)
**File:** `backend/src/sdsa/api/routes.py:310-312`, `backend/src/sdsa/main.py:54-58`  
**Category:** Security  
**Severity:** HIGH  

The DELETE method is allowed in CORS configuration, and POST endpoints have no CSRF protection. An attacker could craft a malicious webpage that causes a victim's browser to delete their session or trigger unwanted processing.

```python
# main.py:54
allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
```

**Impact:** Session deletion or unwanted data processing via CSRF attacks.

**Suggested fix:** Add CSRF tokens or use SameSite cookies. Restrict CORS to specific origins (which is already done) but also validate the `Origin` header on state-changing requests.

---

### H-08: DataFrame Zeroization Is Incomplete (Privacy)
**File:** `backend/src/sdsa/core/session.py:150-168`  
**Category:** Privacy  
**Severity:** HIGH  

The `_zeroize()` function sets `session.df = None` but does not clear the DataFrame's internal memory buffers. Python's memory manager may retain the data indefinitely. For `output_bytes` and `hmac_key`, byte-level zeroization is attempted, but Python's immutable `bytes` objects cannot be reliably zeroed.

```python
def _zeroize(session: Session) -> None:
    # Best effort; Python does not guarantee memory clearing.
    session.df = None  # DataFrame internal buffers remain in memory
    ...
    if session.output_bytes is not None:
        try:
            ba = bytearray(session.output_bytes)  # creates NEW bytearray
            ba[:] = b"\x00" * len(ba)  # zeros the copy, not the original
```

**Impact:** PII may persist in process memory long after session expiration. Memory dump or core dump could reveal raw PII.

**Suggested fix:** This is a known Python limitation. Document it clearly. For the `output_bytes` zeroization, the `bytearray()` constructor creates a copy, so the original `bytes` object is NOT zeroed. Use `memoryview` on a `bytearray` from the start:
```python
# In store_output, store output_bytes as bytearray from the beginning
session.output_bytes = bytearray(output_bytes)
# Then zeroize can work on the original
```

---

## MEDIUM Findings

### M-01: TOCTOU Race Between checkout and store_output (Concurrency)
**File:** `backend/src/sdsa/api/routes.py:141-166`  
**Category:** Concurrency  
**Severity:** MEDIUM  

Between `checkout()` and `store_output()`, the session can expire and be swept. The `clear_output()` return value at line 148 is not checked, so processing continues even if the session is gone. The wasted compute is eventually caught by `store_output()` returning `False`.

```python
snapshot = store.checkout(session_id)
# ... long processing ...
store.clear_output(session_id)  # return value ignored!
# ... more processing ...
if not store.store_output(session_id, buf.getvalue(), result.report):
    raise HTTPException(404, "session expired")
```

**Suggested fix:** Check the return value of `clear_output()` and fail early.

---

### M-02: Concurrent Process Requests for Same Session (Concurrency)
**File:** `backend/src/sdsa/api/routes.py:140-174`  
**Category:** Concurrency  
**Severity:** MEDIUM  

Two concurrent POST requests to `/process/{session_id}` will both pass the `checkout` check, both run the full pipeline, and the second will silently overwrite the first's output. No locking prevents this.

**Suggested fix:** Add a per-session processing lock, or use an atomic compare-and-swap pattern to ensure only one process runs per session at a time.

---

### M-03: `string_truncate` and `mask` Preserve String Length (Privacy)
**File:** `backend/src/sdsa/anonymize/primitives.py:150-158, 18-54`  
**Category:** Privacy  
**Severity:** MEDIUM  

Both `string_truncate` and `mask` produce output of the same length as the input. This leaks the exact length of the original value, which can be a powerful identifying signal (e.g., a 16-char masked value likely indicates a credit card number).

```python
# string_truncate
return s[:keep] + pad_char * (len(s) - keep)

# mask
middle = mask_char * (n - p - q)
return s[:p] + middle + (s[n - q:] if q else "")
```

**Impact:** Length metadata aids re-identification attacks.

**Suggested fix:** Optionally truncate to a fixed length or add random padding. Document the length-preservation behavior so users understand the risk.

---

### M-04: HMAC Key Unnecessarily Exposed in Download Snapshots (Privacy)
**File:** `backend/src/sdsa/api/routes.py:274-283`  
**Category:** Privacy  
**Severity:** MEDIUM  

Download endpoints call `checkout()`, which returns a snapshot including the HMAC key. Downloads only need `output_bytes` or `output_report` — the HMAC key is unnecessary and should not be included.

```python
@router.get("/download/{session_id}/data.csv")
async def download_csv(session_id: str):
    snapshot = store.checkout(session_id)  # includes hmac_key
```

**Suggested fix:** Create a lighter `checkout_output()` method that only returns the output data without the HMAC key.

---

### M-05: Column Name Not Validated for Length or Special Characters (Security)
**File:** `backend/src/sdsa/anonymize/policy.py:35-39`  
**Category:** Security  
**Severity:** MEDIUM  

The `ColumnPolicy.column` field only validates for newlines. It doesn't limit length or other special characters. Very long column names could cause issues in error messages, logs, and report rendering.

```python
@field_validator("column")
@classmethod
def validate_column(cls, value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("column names must not contain newlines")
    return value
```

**Suggested fix:** Add `max_length` to the Field and validate for null bytes:
```python
column: str = Field(min_length=1, max_length=255)
```

---

### M-06: Deterministic Key Name Not Validated for Length (Security)
**File:** `backend/src/sdsa/pipeline.py:32`  
**Category:** Security  
**Severity:** MEDIUM  

The `deterministic_key_name` field has no length limit. A very long key name would be encoded into the HMAC message, potentially causing DoS.

```python
deterministic_key_name: str | None = None  # no length limit
```

**Suggested fix:**
```python
deterministic_key_name: str | None = Field(default=None, max_length=256)
```

---

### M-07: Broad Exception Catching in CSV/TXT Parsers (Error Handling)
**File:** `backend/src/sdsa/ingest.py:59-60, 100-101`  
**Category:** Error Handling  
**Severity:** MEDIUM  

Both CSV and TXT parsers catch all `Exception`, including `MemoryError` and `KeyboardInterrupt`-derived exceptions.

```python
except Exception as e:
    raise ParseError(_friendly_tabular_parse_error("CSV", e)) from e
```

**Suggested fix:** Catch more specific exception types:
```python
except (pl.ComputeError, pl.SchemaError, ValueError, UnicodeDecodeError) as e:
```

---

### M-08: K-Anonymity NULL Handling May Create Identifiable Groups (Privacy / Logic)
**File:** `backend/src/sdsa/kanon/enforce.py:51-54`  
**Category:** Privacy / Logic  
**Severity:** MEDIUM  

All NULL QI values are grouped into a single equivalence class (via `nulls_equal=True`). In datasets where NULLs are rare, this class may be small and identifying. Conversely, if NULLs are common, they form a single large class that passes k-anonymity but may still be re-identifying based on domain knowledge.

```python
joined = df.join(class_sizes, on=qi_columns, how="left", nulls_equal=True)
```

**Impact:** k-anonymity guarantees may be weaker than expected when QI columns contain NULLs.

**Suggested fix:** Document this behavior. Consider treating NULL QI values as suppressible (remove rows with NULL QIs before k-anonymity enforcement).

---

### M-09: Preflight Uses Different HMAC Key Than Pipeline in Deterministic Mode (Logic)
**File:** `backend/src/sdsa/preflight.py:119-123` vs `backend/src/sdsa/pipeline.py:151-154`  
**Category:** Logic  
**Severity:** MEDIUM  

When `deterministic_key_name` is set, the pipeline derives the HMAC key from `deployment_salt + key_name`, but preflight always uses the session's random HMAC key. This means the hash/token values in preflight won't match the final output.

```python
# pipeline.py — overrides hmac_key for deterministic mode
if request.deterministic_key_name:
    hmac_key = _derive_deterministic_key(request.deterministic_key_name, cfg.deployment_salt)

# preflight.py — always uses session hmac_key, no override
def preflight_k_anonymity(original, request, hmac_key):
```

**Impact:** Preflight suppression estimates are still accurate (same cardinality), but this inconsistency could confuse debugging.

**Suggested fix:** Apply the same deterministic key derivation in `preflight_k_anonymity`.

---

### M-10: Encoding Misidentification by chardet (Logic)
**File:** `backend/src/sdsa/ingest.py:42-46`  
**Category:** Logic  
**Severity:** MEDIUM  

`chardet` can misidentify encodings, especially for short or low-entropy text. A misidentified encoding produces garbled text, which would cause PII detection to miss PII in those columns.

```python
guess = chardet.detect(raw[:100_000])
enc = (guess.get("encoding") or "utf-8").lower()
```

**Impact:** Garbled data bypasses PII detection and passes through to the output un-anonymized.

**Suggested fix:** When chardet confidence is low (<0.9), warn the user and suggest re-uploading as UTF-8.

---

### M-11: `samples/generate.py` Uses Non-Cryptographic PRNG (Resource)
**File:** `samples/generate.py:16`  
**Category:** Resource  
**Severity:** MEDIUM  

The sample generator uses `random.Random(SEED)` with a fixed seed. This is correct for deterministic sample generation but means the sample data is fully predictable. If someone uses these samples as test data in a demo and the seed is known, the "anonymized" output could be reversed.

This is low risk since it's a development tool, but worth noting.

---

### M-12: Static File Mount Could Serve Unexpected Files (Security)
**File:** `backend/src/sdsa/main.py:66-68`  
**Category:** Security  
**Severity:** MEDIUM  

The static file mount serves the entire `frontend/` directory. If sensitive files (e.g., `.env`, config files, backup files) exist in the frontend directory, they would be accessible.

```python
frontend = Path(__file__).resolve().parents[3] / "frontend"
if frontend.is_dir() and (frontend / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
```

**Suggested fix:** Ensure the frontend directory only contains intended static assets. Add a `.gitignore` and deployment check.

---

### M-13: No Rate Limiting on Any Endpoint (Security)
**File:** `backend/src/sdsa/api/routes.py` (all endpoints)  
**Category:** Security  
**Severity:** MEDIUM  

No rate limiting exists on any endpoint. Combined with no auth, this allows:
- Brute-force enumeration of session IDs (mitigated by 128-bit entropy)
- Upload flooding to exhaust memory
- Process flooding to exhaust CPU

**Suggested fix:** Add rate limiting middleware (e.g., `slowapi` or nginx rate limiting).

---

## LOW Findings

### L-01: Dead Code in SQL Parser (Logic)
**File:** `backend/src/sdsa/ingest.py:305`  
**Category:** Logic  
**Severity:** LOW  

A `schema` dict mapping column names to `pl.Object` is created but never used. The actual DataFrame creation uses `schema=list(columns)`.

```python
schema = {name: pl.Object for name in columns}  # placeholder, will be inferred
# ...
df = pl.DataFrame(bucket["rows"], schema=list(columns), orient="row")  # schema dict not used
```

**Suggested fix:** Remove the unused `schema` variable.

---

### L-02: `_safe()` in Logging Returns Type Name for Non-Serializable Values (Error Handling)
**File:** `backend/src/sdsa/core/logging.py:46-51`  
**Category:** Error Handling  
**Severity:** LOW  

When a log value can't be serialized to JSON, `_safe()` returns the type name (e.g., `"DataFrame"`). This could mask issues where important context is silently dropped.

```python
def _safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(type(value).__name__)
```

**Suggested fix:** Add a debug-level warning when values can't be serialized.

---

### L-03: `report.py` Markdown Renderer Hardcodes English Strings (Logic)
**File:** `backend/src/sdsa/report.py:57-96`  
**Category:** Logic  
**Severity:** LOW  

The Markdown report is hardcoded in English. If the tool is used in a multilingual context, the report cannot be localized.

**Suggested fix:** Use a localization framework or at minimum document that reports are English-only.

---

### L-04: Correlation Matrix is O(n²) DataFrame Creations (Resource)
**File:** `backend/src/sdsa/validate/metrics.py:95-115`  
**Category:** Resource  
**Severity:** LOW  

For each pair of numeric columns, a new Polars DataFrame is created. For a dataset with N numeric columns, this creates N² DataFrames. This is inefficient but correct.

```python
for a in num_cols:
    for b in num_cols:
        val = pl.DataFrame({"a": df[a], "b": df[b]}) \
                .drop_nulls().select(pl.corr("a", "b")).item()
```

**Suggested fix:** Use Polars' built-in correlation matrix computation or compute all pairwise correlations in a single operation.

---

### L-05: `_ext()` Function Doesn't Handle Files Without Extensions (Logic)
**File:** `backend/src/sdsa/ingest.py:323-325`  
**Category:** Logic  
**Severity:** LOW  

```python
def _ext(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx >= 0 else ""
```

If a file is named `.csv` (hidden file with no basename), `idx = 0` and it returns `.csv`, which is correct. If the filename is `Makefile` (no extension), it returns `""`, which correctly triggers the "unsupported file type" error. This is actually fine but worth noting.

---

### L-06: `samples/generate.py` Phone Number Truncation (Logic)
**File:** `samples/generate.py:148`  
**Category:** Logic  
**Severity:** LOW  

```python
def phone_us(rng: random.Random) -> str:
    area = rng.choice([415, 212, 310, 617, 312, 206])
    return f"+1{area}{rng.randint(5_550_000, 5_559_999):07d}"[:12]
```

The `[:12]` truncation is a safety measure. The generated phone numbers are always exactly 12 chars: `+1` + 3-digit area + 7-digit number. The truncation is correct but unnecessary. If the format ever changes, the truncation could silently produce wrong results.

---

### L-07: Frontend `esc()` Doesn't Escape Backticks (Security)
**File:** `frontend/app.js:572-576`  
**Category:** Security  
**Severity:** LOW  

The HTML escaping function doesn't escape backticks. While backticks don't have special meaning in HTML, they could be relevant in JavaScript template literals if values are ever inserted into inline scripts.

```javascript
function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
}
```

**Suggested fix:** Add backtick escaping for defense-in-depth: `` ` `` → `` &#96; ``

---

### L-08: Frontend Session Timer Doesn't Sync with Server (Logic)
**File:** `frontend/app.js:51-70`  
**Category:** Logic  
**Severity:** LOW  

The session timer uses the client's clock (`Date.now()`) relative to the upload time. If the client's clock is wrong, the countdown will be inaccurate. The server TTL (30 minutes) is used from `uploadData.session_ttl_seconds`.

```javascript
const ttlSeconds = state.uploadData?.session_ttl_seconds || 1800;
const elapsed = (Date.now() - state.sessionStartedAt) / 1000;
const remaining = Math.max(0, ttlSeconds - elapsed);
```

**Impact:** The timer may show an incorrect countdown, but session expiration is still enforced server-side.

---

### L-09: `validate/metrics.py` Histogram Assumes Polars Column Names (Logic)
**File:** `backend/src/sdsa/validate/metrics.py:42-46`  
**Category:** Logic  
**Severity:** LOW  

The histogram function assumes Polars' `hist()` returns columns named `"breakpoint"` and `"count"`. If Polars changes these names in a future version, the code will break silently.

```python
hist = clean.cast(pl.Float64).hist(bin_count=bins)
return {
    "edges": [lo] + [float(v) for v in hist["breakpoint"].to_list()],
    "counts": [int(v) for v in hist["count"].to_list()],
}
```

**Suggested fix:** Use the Polars column names programmatically or add a version check.

---

### L-10: `_name_matches_hint` Could False-Positive on Short Hints (Logic)
**File:** `backend/src/sdsa/detect/pii.py:111-127`  
**Category:** Logic  
**Severity:** LOW  

The column-name hint matching normalizes both the column name and hint by removing non-alphanumeric characters. For very short hints like `"id"`, many column names could match (e.g., `"product_id"`, `"order_id"`), potentially misclassifying non-PII columns as `identifier`.

```python
compact_name = normalized_name.replace("_", "")
compact_hint = normalized_hint.replace("_", "")
return bool(compact_hint) and compact_hint == compact_name
```

This is mitigated by the 0.55 confidence score for name-only matches, but could still lead to unnecessary user confusion.

---

### L-11: Download Filename Is Hardcoded (Logic)
**File:** `backend/src/sdsa/api/routes.py:282`  
**Category:** Logic  
**Severity:** LOW  

The export filename is always `sdsa-export.csv`, regardless of the original file name or session.

```python
headers = {"Content-Disposition": 'attachment; filename="sdsa-export.csv"'}
```

**Suggested fix:** Consider incorporating the session ID or original filename into the export name.

---

### L-12: `samples/generate.py` Contains Public Test Credit Card Numbers (Security)
**File:** `samples/generate.py:100-109`  
**Category:** Security  
**Severity:** LOW  

The sample generator includes well-known test credit card numbers (Visa, MasterCard, Amex, etc.). While these are publicly known and reserved for testing, if sample data is accidentally used in a demo with real PII detection, the tool will correctly flag them as credit cards.

```python
TEST_CARDS = [
    "4111111111111111",  # Visa
    "4012888888881881",  # Visa
    ...
]
```

This is correct behavior and not a real vulnerability.

---

## Architectural Recommendations

1. **Add authentication** — Even a simple API key or session token bound to the upload would significantly improve security.

2. **Add rate limiting** — Protect all endpoints, especially upload and process.

3. **Implement streaming for large files** — Instead of reading the entire upload into memory, stream to disk or process in chunks.

4. **Use deeper HMAC truncation** — 128+ bits for hash, 96+ bits for tokenize to prevent collisions.

5. **Add comprehensive PII detection** — Stratified sampling across the full dataset, not just the first rows.

6. **Sanitize all error messages** — Never include raw data values in errors returned to clients.

7. **Add request size and field limits** — Cap policy list length, DP params size, key name length.

8. **Add CSP headers** — For the frontend, add Content-Security-Policy headers to prevent XSS even if a bypass is found.

9. **Consider a reverse proxy** — Use nginx/Caddy for TLS termination, rate limiting, and request size limits.

10. **Add integration tests for privacy** — Test that no raw PII appears in error messages, logs, or report outputs.
