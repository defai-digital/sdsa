from __future__ import annotations

import math

import polars as pl

from sdsa.validate.metrics import _histogram, _numeric_stats


def test_histogram_excludes_nan_values():
    s = pl.Series("val", [1.0, 2.0, float("nan"), 3.0, 4.0])
    hist = _histogram(s)
    assert sum(hist["counts"]) == 4


def test_numeric_stats_do_not_emit_nan():
    s = pl.Series("val", [1.0, 2.0, float("nan"), 3.0, 4.0])
    stats = _numeric_stats(s)
    assert all(v is None or math.isfinite(v) for k, v in stats.items() if k != "null_ratio")
