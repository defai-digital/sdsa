"""PII detection: regex + libphonenumber + column-name heuristics (ADR-0005).

Detectors return a confidence score in [0, 1]. Results are suggestions —
the user confirms before processing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import phonenumbers
import polars as pl

PIIKind = Literal[
    "email", "phone", "credit_card", "government_id",
    "name", "address", "date_of_birth", "identifier", "none",
]


@dataclass
class PIISuggestion:
    kind: PIIKind
    confidence: float
    reason: str


# RFC 5322-lite; good precision, decent recall.
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)

CREDIT_CARD_RE = re.compile(r"^\d{13,19}$")

# Multilingual column-name hints (lowercased comparison).
COLUMN_NAME_HINTS: dict[PIIKind, tuple[str, ...]] = {
    "email": ("email", "e-mail", "mail", "電子郵件", "邮箱", "メール"),
    "phone": ("phone", "tel", "mobile", "cell", "電話", "手机", "手機", "電話番号"),
    "name": ("name", "fullname", "first_name", "last_name", "surname",
             "姓名", "名字", "名前", "full name"),
    "address": ("address", "addr", "street", "city", "zip", "postal",
                "住址", "地址", "住所"),
    "government_id": ("ssn", "nric", "id_number", "national_id",
                      "身分證", "身份证", "マイナンバー", "taxid", "tax_id"),
    "date_of_birth": ("dob", "birthdate", "birth_date", "birthday",
                      "生日", "誕生日"),
    "credit_card": ("credit_card", "card_number", "ccnum", "card"),
    "identifier": ("user_id", "customer_id", "account_id", "uuid", "guid"),
}


def luhn_valid(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not digits:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _sample_strings(series: pl.Series, n: int = 200) -> list[str]:
    s = series.drop_nulls()
    if s.len() == 0:
        return []
    s = s.cast(pl.Utf8, strict=False).drop_nulls()
    if s.len() == 0:
        return []
    take = min(n, s.len())
    return s.head(take).to_list()


def _ratio(predicate, values: list[str]) -> float:
    if not values:
        return 0.0
    hits = sum(1 for v in values if v and predicate(v))
    return hits / len(values)


def _is_email(v: str) -> bool:
    return bool(EMAIL_RE.match(v.strip()))


def _is_phone(v: str) -> bool:
    v = v.strip()
    if not v:
        return False
    try:
        # Try with region None first (needs +); fall back to common defaults.
        for region in (None, "US", "TW", "GB"):
            try:
                num = phonenumbers.parse(v, region)
            except phonenumbers.NumberParseException:
                continue
            if phonenumbers.is_valid_number(num):
                return True
        return False
    except Exception:
        return False


def _is_credit_card(v: str) -> bool:
    compact = v.replace(" ", "").replace("-", "")
    return bool(CREDIT_CARD_RE.match(compact)) and luhn_valid(compact)


def _name_matches_hint(column_name: str, hint: str) -> bool:
    if not hint.isascii():
        return hint in column_name

    normalized_name = re.sub(r"[^a-z0-9]+", "_", column_name)
    normalized_hint = re.sub(r"[^a-z0-9]+", "_", hint.lower())

    if normalized_hint == normalized_name:
        return True

    tokens = tuple(token for token in normalized_name.split("_") if token)
    if normalized_hint in tokens:
        return True

    compact_name = normalized_name.replace("_", "")
    compact_hint = normalized_hint.replace("_", "")
    return bool(compact_hint) and compact_hint == compact_name


def detect_column(name: str, series: pl.Series) -> PIISuggestion:
    """Return the best PII suggestion for one column."""
    samples = _sample_strings(series)
    name_lower = name.lower().strip()

    # Column-name hint pass (gives a confidence floor).
    name_hint_kind: PIIKind = "none"
    for kind, hints in COLUMN_NAME_HINTS.items():
        if any(_name_matches_hint(name_lower, hint) for hint in hints):
            name_hint_kind = kind
            break

    # Content-based tests.
    candidates: list[tuple[PIIKind, float, str]] = []

    if samples:
        email_ratio = _ratio(_is_email, samples)
        if email_ratio >= 0.80:
            candidates.append(("email", min(0.99, email_ratio), f"{email_ratio:.0%} match email regex"))

        phone_ratio = _ratio(_is_phone, samples)
        if phone_ratio >= 0.70:
            candidates.append(("phone", min(0.95, phone_ratio), f"{phone_ratio:.0%} parse as valid phone"))

        cc_ratio = _ratio(_is_credit_card, samples)
        if cc_ratio >= 0.70:
            candidates.append(("credit_card", min(0.99, cc_ratio),
                               f"{cc_ratio:.0%} pass Luhn"))

    # High-cardinality string with distinct values often = identifier.
    if series.dtype == pl.Utf8 and series.len() > 0:
        n = series.len()
        u = series.n_unique()
        if u / max(n, 1) > 0.95 and n > 20 and not candidates:
            candidates.append(("identifier", 0.60, "high cardinality string"))

    # Merge with column-name hint.
    if name_hint_kind != "none":
        existing = next((c for c in candidates if c[0] == name_hint_kind), None)
        if existing:
            # Boost confidence when name + content agree.
            kind, conf, reason = existing
            candidates = [c for c in candidates if c[0] != kind]
            candidates.append((kind, min(0.99, conf + 0.10), f"{reason} + column name"))
        else:
            candidates.append((name_hint_kind, 0.55, "column name hint only"))

    if not candidates:
        return PIISuggestion("none", 1.0, "no PII signal")

    candidates.sort(key=lambda c: c[1], reverse=True)
    kind, conf, reason = candidates[0]
    return PIISuggestion(kind, conf, reason)


def detect_dataframe(df: pl.DataFrame) -> dict[str, PIISuggestion]:
    return {col: detect_column(col, df[col]) for col in df.columns}
