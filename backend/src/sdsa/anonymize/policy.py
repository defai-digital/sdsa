"""Column policy model + apply function.

A ColumnPolicy describes how one column should be transformed. The pipeline
iterates over policies and invokes the matching primitive or DP mechanism.
"""
from __future__ import annotations

from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field

from . import primitives as prim

Action = Literal[
    "retain", "mask", "hash", "tokenize", "redact",
    "numeric_bin", "date_truncate", "string_truncate",
    "dp_laplace",
    "drop",
]


class PolicyApplicationError(ValueError):
    pass


class ColumnPolicy(BaseModel):
    column: str
    action: Action
    params: dict[str, Any] = Field(default_factory=dict)
    is_quasi_identifier: bool = False

    # For dp_laplace: caller must supply `epsilon` and column bounds `lower`/`upper`.


def apply_policy(df: pl.DataFrame, policy: ColumnPolicy, hmac_key: bytes) -> pl.DataFrame:
    """Apply a single non-DP policy to a DataFrame. DP is applied separately."""
    col = policy.column
    if col not in df.columns:
        return df
    s = df[col]
    action = policy.action
    p = policy.params

    try:
        if action == "retain":
            return df
        if action == "drop":
            return df.drop(col)
        if action == "mask":
            out = prim.mask(s, keep_prefix=p.get("keep_prefix", 0),
                           keep_suffix=p.get("keep_suffix", 0),
                           mask_char=p.get("mask_char", "*"))
        elif action == "hash":
            out = prim.hmac_hash(s, hmac_key)
        elif action == "tokenize":
            out = prim.tokenize(s, hmac_key, prefix=p.get("prefix", "tok_"))
        elif action == "redact":
            out = prim.redact(s, replacement=p.get("replacement", "[REDACTED]"))
        elif action == "numeric_bin":
            if "bin_width" not in p:
                raise PolicyApplicationError(
                    f"column '{col}' with action 'numeric_bin' requires param 'bin_width'"
                )
            out = prim.numeric_bin(s, bin_width=float(p["bin_width"]))
        elif action == "date_truncate":
            out = prim.date_truncate(s, granularity=p.get("granularity", "month"))
        elif action == "string_truncate":
            out = prim.string_truncate(s, keep=int(p.get("keep", 3)),
                                       pad_char=p.get("pad_char", "*"))
        elif action == "dp_laplace":
            # Applied by the DP pass, not here.
            return df
        else:
            raise PolicyApplicationError(f"unknown action {action}")
    except PolicyApplicationError:
        raise
    except (KeyError, TypeError, ValueError) as e:
        raise PolicyApplicationError(
            f"invalid params for column '{col}' action '{action}': {e}"
        ) from e

    return df.with_columns(out.alias(col))
