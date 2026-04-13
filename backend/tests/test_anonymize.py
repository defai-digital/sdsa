from __future__ import annotations

import polars as pl

from sdsa.anonymize.primitives import (
    date_truncate,
    hmac_hash,
    mask,
    new_session_key,
    numeric_bin,
    redact,
    string_truncate,
    tokenize,
)


def test_mask_full():
    s = pl.Series("x", ["abcdef", "hi"])
    out = mask(s).to_list()
    assert out == ["******", "**"]


def test_mask_keep_prefix_suffix():
    s = pl.Series("x", ["abcdef"])
    out = mask(s, keep_prefix=1, keep_suffix=1).to_list()
    assert out == ["a****f"]


def test_hmac_is_deterministic_per_key():
    key = new_session_key()
    s = pl.Series("x", ["alice", "bob", "alice"])
    out = hmac_hash(s, key).to_list()
    assert out[0] == out[2]
    assert out[0] != out[1]


def test_hmac_changes_with_key():
    s = pl.Series("x", ["alice"])
    a = hmac_hash(s, new_session_key()).to_list()[0]
    b = hmac_hash(s, new_session_key()).to_list()[0]
    assert a != b


def test_tokenize_prefix():
    key = new_session_key()
    s = pl.Series("x", ["alice"])
    out = tokenize(s, key, prefix="u_").to_list()[0]
    assert out.startswith("u_")


def test_redact_replaces_nonnull_only():
    s = pl.Series("x", ["secret", None, "more"])
    out = redact(s).to_list()
    assert out == ["[REDACTED]", None, "[REDACTED]"]


def test_numeric_bin_buckets():
    s = pl.Series("age", [22.0, 25.0, 34.0, 99.0])
    out = numeric_bin(s, bin_width=10).to_list()
    assert out[0] == out[1]  # both in [20, 30)
    assert out[2] != out[0]


def test_date_truncate_to_month():
    import datetime as dt
    s = pl.Series("d", [dt.date(2026, 4, 12), dt.date(2026, 4, 1)])
    out = date_truncate(s, "month").to_list()
    assert out == ["2026-04", "2026-04"]


def test_string_truncate():
    s = pl.Series("zip", ["12345"])
    out = string_truncate(s, keep=3).to_list()
    assert out == ["123**"]
