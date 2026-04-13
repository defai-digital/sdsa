from __future__ import annotations

import polars as pl

from sdsa.detect.pii import detect_column, detect_dataframe, luhn_valid
from sdsa.detect.schema import infer_schema


def test_email_detected_with_high_confidence():
    s = pl.Series("email", ["alice@example.com", "bob@foo.org", "carol@baz.co"])
    sug = detect_column("email", s)
    assert sug.kind == "email"
    assert sug.confidence >= 0.90


def test_phone_detected():
    s = pl.Series("contact", ["+14155552671", "+442071838750", "+886223112222"])
    sug = detect_column("contact", s)
    assert sug.kind == "phone"


def test_credit_card_luhn():
    # 4111 1111 1111 1111 is the canonical Visa test number (valid Luhn).
    assert luhn_valid("4111111111111111")
    s = pl.Series("card", ["4111111111111111", "5500000000000004", "340000000000009"])
    sug = detect_column("card", s)
    assert sug.kind == "credit_card"


def test_column_name_hint_only():
    # Values look like gibberish but column name hints 'email'.
    s = pl.Series("Email", ["xxx", "yyy", "zzz"])
    sug = detect_column("Email", s)
    assert sug.kind == "email"
    # Name-hint only → lower confidence band
    assert sug.confidence <= 0.80


def test_no_pii_when_numeric_and_no_hint():
    s = pl.Series("age", [22, 35, 41, 29])
    sug = detect_column("age", s)
    assert sug.kind == "none"


def test_schema_infers_numeric_vs_string():
    df = pl.DataFrame({"age": [20, 30, 40], "name": ["a", "b", "c"]})
    schema = infer_schema(df)
    kinds = {c["name"]: c["kind"] for c in schema}
    assert kinds["age"] == "numeric"
    assert kinds["name"] in ("string", "categorical")


def test_detect_dataframe_returns_one_per_column():
    df = pl.DataFrame({
        "email": ["a@b.com", "c@d.com"],
        "age": [10, 20],
    })
    out = detect_dataframe(df)
    assert set(out) == {"email", "age"}


def test_mailing_address_does_not_hit_email_hint():
    s = pl.Series("mailing_address", ["123 Main St", "456 Oak Ave", "789 Pine Rd"])
    sug = detect_column("mailing_address", s)
    assert sug.kind == "address"


def test_user_email_still_hits_email_hint():
    s = pl.Series("user_email", ["not-an-email", "still-not", "nope"])
    sug = detect_column("user_email", s)
    assert sug.kind == "email"
