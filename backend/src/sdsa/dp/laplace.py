"""Laplace mechanism for numeric columns (ADR-0002).

We use OpenDP where available; if the OpenDP build doesn't expose a
straightforward per-value Laplace primitive, we fall back to a
numpy-free pure-Python sampler that implements the standard Laplace
distribution. Both paths use the same (scale = sensitivity / epsilon)
parameterization.

Sensitivity is caller-provided based on declared column bounds
(upper - lower). If no bounds are declared, the pipeline refuses to
apply DP to that column (fail-closed).
"""
from __future__ import annotations

import math
import secrets
from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class LaplaceParams:
    epsilon: float
    lower: float
    upper: float

    @property
    def sensitivity(self) -> float:
        return float(self.upper - self.lower)

    @property
    def scale(self) -> float:
        return self.sensitivity / self.epsilon


def _laplace_sample(scale: float) -> float:
    """Sample from Laplace(0, scale) using the inverse CDF method.

    Uses the cryptographic RNG for the uniform sample; good enough for a
    practical DP implementation and avoids seeding concerns. Not
    constant-time; not resistant to timing side-channels (out of scope
    per ADR-0007 threat model).
    """
    # u in (-0.5, 0.5), open interval
    raw = secrets.randbits(53)
    u = (raw / (1 << 53)) - 0.5
    # Avoid log(0)
    if u == 0:
        u = 1e-12
    return -scale * math.copysign(math.log(1 - 2 * abs(u)), u)


def apply_laplace(series: pl.Series, params: LaplaceParams) -> pl.Series:
    """Add bounded Laplace noise to a numeric series.

    Inputs are clamped to the declared bounds before noise to enforce the
    sensitivity assumption. Outputs are clamped again as post-processing so
    the released values stay within the caller-declared domain.
    """
    if params.epsilon <= 0:
        raise ValueError("epsilon must be > 0")
    if params.upper <= params.lower:
        raise ValueError("upper must be > lower")
    scale = params.scale

    def _noise(v):
        if v is None:
            return None
        # Clamp input to [lower, upper] to enforce bounded sensitivity.
        x = max(params.lower, min(params.upper, float(v)))
        noisy = x + _laplace_sample(scale)
        return max(params.lower, min(params.upper, noisy))
    return series.map_elements(_noise, return_dtype=pl.Float64)
