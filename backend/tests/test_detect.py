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


def test_numeric_luhn_ids_do_not_trigger_credit_card_detection():
    s = pl.Series("transaction_id", [4111111111111111, 4012888888881881, 5555555555554444])
    sug = detect_column("transaction_id", s)
    assert sug.kind != "credit_card"


def test_id_like_numeric_column_flagged_as_identifier():
    # The case that previously fell through to retain: a near-unique numeric *_id.
    s = pl.Series("employee_id", list(range(1000, 1050)))
    sug = detect_column("employee_id", s)
    assert sug.kind == "identifier"
    assert sug.confidence >= 0.85  # near-unique strengthens the signal


def test_bare_and_suffixed_id_columns_flagged_as_identifier():
    assert detect_column("id", pl.Series("id", [1, 2, 3, 4, 5])).kind == "identifier"
    assert detect_column("order_id", pl.Series("order_id", [9, 8, 7])).kind == "identifier"
    assert detect_column("record_uuid", pl.Series("record_uuid", ["a", "b"])).kind == "identifier"


def test_id_substring_does_not_false_positive():
    # "paid"/"valid" contain "id" as a substring but not as a whole token.
    assert detect_column("paid", pl.Series("paid", [1.0, 2.0, 3.0])).kind != "identifier"
    assert detect_column("valid", pl.Series("valid", [True, False, True])).kind != "identifier"


def test_low_cardinality_id_column_is_kept_for_analysis():
    # Foreign-key style code: many rows, few distinct values. Should NOT be
    # flagged as an identifier, so it stays analysable in cleartext.
    s = pl.Series("department_id", [1, 2, 3, 1, 2, 3] * 20)  # 120 rows, 3 distinct
    assert detect_column("department_id", s).kind != "identifier"


def test_low_cardinality_specific_id_hint_also_kept():
    # Even a specific hint name (customer_id) is kept when it is a low-card code.
    s = pl.Series("customer_id", [10, 20, 30] * 40)  # 120 rows, 3 distinct
    assert detect_column("customer_id", s).kind != "identifier"


def test_specific_pii_name_keeps_priority_over_generic_id_rule():
    # national_id must stay government_id (hashed), not the generic identifier.
    s = pl.Series("national_id", ["S1234567A", "T7654321B"])
    assert detect_column("national_id", s).kind == "government_id"
