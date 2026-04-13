"""Input format parsers: CSV, delimited TXT, and SQL `INSERT` dumps.

Dispatcher `parse_upload(filename, raw)` picks a parser from the file
extension. Each parser returns a Polars DataFrame plus a short metadata
dict describing what it did (delimiter used, table name, etc.).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

import chardet
import polars as pl


@dataclass
class ParseResult:
    df: pl.DataFrame
    format: str              # "csv" | "txt" | "sql"
    encoding: str
    meta: dict[str, Any]     # format-specific details


class ParseError(ValueError):
    pass


# --- encoding ----------------------------------------------------------------

def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # Prefer UTF-8 when the bytes are valid UTF-8. chardet sometimes
    # misidentifies low-entropy ASCII as UTF-7, which then fails to decode.
    try:
        raw[:100_000].decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    guess = chardet.detect(raw[:100_000])
    enc = (guess.get("encoding") or "utf-8").lower()
    if enc == "ascii":
        return "utf-8"
    return enc


# --- CSV ---------------------------------------------------------------------

def parse_csv(text: str) -> ParseResult:
    try:
        df = pl.read_csv(
            io.StringIO(text),
            infer_schema_length=1000,
            try_parse_dates=True,
            null_values=["", "NA", "N/A", "null", "NULL"],
        )
    except Exception as e:
        raise ParseError(f"CSV parse failed: {e}")
    if df.height == 0:
        raise ParseError("CSV contains no rows")
    return ParseResult(df=df, format="csv", encoding="", meta={"delimiter": ","})


# --- TXT (delimited) ---------------------------------------------------------

_DELIM_CANDIDATES = ("\t", "|", ";", ",")


def sniff_delimiter(text: str) -> str:
    """Pick the delimiter that appears a consistent, non-zero number of times
    across the first few non-blank lines."""
    head = [ln for ln in text.splitlines()[:10] if ln.strip()][:5]
    if not head:
        return ","
    best = ","
    best_count = 0
    for cand in _DELIM_CANDIDATES:
        counts = [ln.count(cand) for ln in head]
        if counts and all(c == counts[0] for c in counts) and counts[0] > best_count:
            best = cand
            best_count = counts[0]
    return best


def parse_txt(text: str) -> ParseResult:
    delim = sniff_delimiter(text)
    try:
        df = pl.read_csv(
            io.StringIO(text),
            separator=delim,
            infer_schema_length=1000,
            try_parse_dates=True,
            null_values=["", "NA", "N/A", "null", "NULL"],
        )
    except Exception as e:
        raise ParseError(f"TXT parse failed (delimiter '{delim}'): {e}")
    if df.height == 0:
        raise ParseError("TXT contains no rows")
    return ParseResult(df=df, format="txt", encoding="",
                       meta={"delimiter": delim})


# --- SQL INSERT dump ---------------------------------------------------------

_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([\w.\"`]+)\s*(?:\(([^)]+)\))?\s*VALUES\s*",
    re.IGNORECASE,
)
_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_sql_comments(text: str) -> str:
    text = _COMMENT_BLOCK.sub("", text)
    text = _COMMENT_LINE.sub("", text)
    return text


def _parse_column_list(spec: str) -> list[str]:
    return [c.strip().strip('`"[] ') for c in spec.split(",") if c.strip()]


def _parse_string(text: str, i: int) -> tuple[str, int]:
    quote = text[i]
    i += 1
    n = len(text)
    buf: list[str] = []
    escapes = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
               "'": "'", '"': '"', "0": "\x00"}
    while i < n:
        c = text[i]
        if c == quote:
            if i + 1 < n and text[i + 1] == quote:
                buf.append(quote)
                i += 2
                continue
            return "".join(buf), i + 1
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in escapes:
                buf.append(escapes[nxt])
                i += 2
                continue
        buf.append(c)
        i += 1
    raise ParseError("unterminated string literal")


def _parse_value(text: str, i: int) -> tuple[Any, int]:
    n = len(text)
    while i < n and text[i] in " \t\n\r":
        i += 1
    if i >= n:
        raise ParseError("unexpected end of VALUES")
    c = text[i]
    if c in "'\"":
        return _parse_string(text, i)
    start = i
    while i < n and text[i] not in ",) \t\n\r":
        i += 1
    token = text[start:i]
    upper = token.upper()
    if upper == "NULL":
        return None, i
    if upper in ("TRUE", "FALSE"):
        return upper == "TRUE", i
    try:
        if any(ch in token for ch in ".eE"):
            return float(token), i
        return int(token), i
    except ValueError:
        return token, i  # unknown literal kept as string


def _parse_row_tuples(text: str, start: int) -> tuple[list[list], int]:
    """Parse `(v,v,...), (v,v,...) ;` starting at position `start`.
    Return (rows, index-after-terminator)."""
    i = start
    n = len(text)
    rows: list[list] = []
    while i < n:
        while i < n and text[i] in " \t\n\r":
            i += 1
        if i >= n:
            break
        if text[i] == ";":
            return rows, i + 1
        if text[i] == ",":
            i += 1
            continue
        if text[i] != "(":
            break
        i += 1  # consume (
        row: list[Any] = []
        closed = False
        while i < n:
            while i < n and text[i] in " \t\n\r":
                i += 1
            if i < n and text[i] == ")":
                i += 1
                closed = True
                break
            val, i = _parse_value(text, i)
            row.append(val)
            while i < n and text[i] in " \t\n\r":
                i += 1
            if i < n and text[i] == ",":
                i += 1
        if not closed:
            raise ParseError(
                "unterminated row tuple in VALUES clause — expected ')'"
            )
        rows.append(row)
    return rows, i


def parse_sql(text: str) -> ParseResult:
    text = _strip_sql_comments(text)
    tables: dict[tuple, dict] = {}  # signature -> {name, rows}
    i = 0
    n = len(text)
    found = False
    while i < n:
        m = _INSERT_RE.search(text, i)
        if not m:
            break
        found = True
        table = m.group(1).strip('`"')
        col_spec = m.group(2)
        columns = tuple(_parse_column_list(col_spec)) if col_spec else None
        rows, end = _parse_row_tuples(text, m.end())
        if not rows:
            i = end
            continue
        if columns is None:
            columns = tuple(f"col_{k}" for k in range(len(rows[0])))
        key = (table, columns)
        bucket = tables.setdefault(key, {"name": table, "columns": list(columns), "rows": []})
        # Normalize row widths
        for r in rows:
            if len(r) != len(columns):
                raise ParseError(
                    f"row in INSERT INTO {table} has {len(r)} values, "
                    f"expected {len(columns)}"
                )
            bucket["rows"].append(r)
        i = end

    if not found:
        raise ParseError("no INSERT statements found")
    if not tables:
        raise ParseError("INSERT statements had no rows")
    if len(tables) > 1:
        names = sorted({t["name"] for t in tables.values()})
        raise ParseError(
            f"multi-table dumps not supported; found tables: {names}. "
            f"Split the file and upload one table at a time."
        )

    (table_name, columns), bucket = next(iter(tables.items()))
    # Build DataFrame row-wise. Polars needs a consistent schema; infer loosely.
    schema = {name: pl.Object for name in columns}  # placeholder, will be inferred
    try:
        df = pl.DataFrame(bucket["rows"], schema=list(columns), orient="row")
    except Exception as e:
        raise ParseError(f"could not assemble DataFrame: {e}")
    if df.height == 0:
        raise ParseError("SQL dump contained no data rows")
    return ParseResult(
        df=df, format="sql", encoding="",
        meta={"table": table_name, "row_count": df.height},
    )


# --- dispatcher --------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".csv", ".txt", ".sql"}


def _ext(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx >= 0 else ""


def parse_upload(filename: str, raw: bytes) -> ParseResult:
    if not raw:
        raise ParseError("empty file")
    encoding = detect_encoding(raw)
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as e:
        raise ParseError(f"decode failed ({encoding}): {e}")
    ext = _ext(filename)
    if ext == ".csv":
        result = parse_csv(text)
    elif ext == ".txt":
        result = parse_txt(text)
    elif ext == ".sql":
        result = parse_sql(text)
    else:
        raise ParseError(
            f"unsupported file type '{ext or '?'}'. Expected one of: "
            f"{sorted(SUPPORTED_EXTENSIONS)}"
        )
    return ParseResult(df=result.df, format=result.format,
                       encoding=encoding, meta=result.meta)
