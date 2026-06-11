from __future__ import annotations

import polars as pl
import pytest

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
from sdsa.anonymize.policy import ColumnPolicy


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


def test_numeric_bin_handles_decimal_boundaries():
    s = pl.Series("x", [0.1, 1.0, 2.0])
    out = numeric_bin(s, bin_width=0.1).to_list()
    assert out == ["[0.1, 0.2)", "[1, 1.1)", "[2, 2.1)"]


def test_date_truncate_to_month():
    import datetime as dt
    s = pl.Series("d", [dt.date(2026, 4, 12), dt.date(2026, 4, 1)])
    out = date_truncate(s, "month").to_list()
    assert out == ["2026-04", "2026-04"]


def test_string_truncate():
    s = pl.Series("zip", ["12345"])
    out = string_truncate(s, keep=3).to_list()
    assert out == ["123**"]


def test_mask_enforces_at_least_one_char_masked_on_short_values():
    """Regression (privacy leak): mask(s, keep_prefix=5) used to return 'hi'
    unchanged because p = min(5, 2) = 2 consumed the whole string and the
    middle slice was empty. At least one character must always be masked."""
    s = pl.Series("x", ["hi", "abc", "abcdef"])
    out = mask(s, keep_prefix=5, keep_suffix=0).to_list()
    for original, masked in zip(["hi", "abc", "abcdef"], out):
        assert "*" in masked, f"{original!r} → {masked!r} has no mask chars"


def test_mask_scales_prefix_plus_suffix_for_short_strings():
    """When keep_prefix + keep_suffix >= len(s), both are scaled down so at
    least one character is masked, but the ratio between them is preserved."""
    s = pl.Series("x", ["abcde"])  # length 5
    # 4 + 4 = 8 >= 5 → scale so they sum to 4; ratio 1:1 → p=q=2
    out = mask(s, keep_prefix=4, keep_suffix=4).to_list()[0]
    assert out.count("*") >= 1
    assert out[:2] == "ab"


def test_mask_rejects_negative_params():
    s = pl.Series("x", ["abcdef"])
    try:
        mask(s, keep_prefix=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError for negative keep_prefix")


def test_date_truncate_parses_non_iso_strings():
    """Non-ISO date strings (columns Polars couldn't auto-parse) are now
    actually truncated instead of silently passed through."""
    s = pl.Series("dob", ["15/01/2026", "March 5, 2025"])
    out = date_truncate(s, "year").to_list()
    assert out == ["2026", "2025"]


def test_date_truncate_raises_on_unparseable_string():
    """Regression (privacy): previously date_truncate fell back to
    str(v), silently leaking the original date for non-ISO or malformed
    values. Now it raises so the pipeline returns a 400."""
    s = pl.Series("dob", ["not a date at all"])
    try:
        date_truncate(s, "year").to_list()
    except ValueError as e:
        assert "date_truncate" in str(e).lower() or "cannot parse" in str(e).lower()
        return
    # map_elements may lazy-evaluate; force realization if no error yet
    raise AssertionError("expected ValueError for unparseable value")


def test_column_policy_rejects_empty_and_multiline_names():
    with pytest.raises(Exception):
        ColumnPolicy(column="", action="retain")
    with pytest.raises(Exception):
        ColumnPolicy(column="bad\nname", action="retain")
