from __future__ import annotations

import statistics

import polars as pl

from sdsa.dp.accountant import Accountant
from sdsa.dp.laplace import LaplaceParams, apply_laplace


def test_laplace_mean_approaches_input_with_enough_samples():
    # With small sensitivity/epsilon ratio, noise averages out.
    n = 5000
    values = [50.0] * n
    s = pl.Series("x", values)
    params = LaplaceParams(epsilon=2.0, lower=0.0, upper=100.0)  # scale = 50
    out = apply_laplace(s, params)
    mean = statistics.mean(out.to_list())
    # Mean of n Laplace(0, 50) samples has std ~ 50 * sqrt(2) / sqrt(n) ~ 1.0
    assert 40 < mean < 60


def test_laplace_clamps_input():
    # Inputs outside [lower, upper] must be clamped before noise.
    s = pl.Series("x", [1_000_000.0])  # way out of range
    params = LaplaceParams(epsilon=1.0, lower=0.0, upper=10.0)
    out = apply_laplace(s, params).to_list()[0]
    assert 0.0 <= out <= 10.0


def test_laplace_clamps_noised_output_to_bounds():
    s = pl.Series("x", [0.0] * 200)
    params = LaplaceParams(epsilon=0.1, lower=-5.0, upper=5.0)
    out = apply_laplace(s, params).to_list()
    assert all(-5.0 <= v <= 5.0 for v in out if v is not None)


def test_laplace_rejects_bad_params():
    s = pl.Series("x", [1.0])
    try:
        apply_laplace(s, LaplaceParams(epsilon=0, lower=0, upper=1))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for epsilon=0")

    try:
        apply_laplace(s, LaplaceParams(epsilon=1, lower=5, upper=5))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for upper==lower")


def test_accountant_tracks_per_column():
    a = Accountant()
    a.charge("age", 0.5)
    a.charge("age", 0.5)
    a.charge("salary", 1.0)
    snap = a.snapshot()
    assert snap["age"] == 1.0
    assert snap["salary"] == 1.0
    assert a.max_epsilon() == 1.0


def test_laplace_sampler_handles_boundary_rng_outputs():
    """Regression: previous implementation crashed with math domain error
    when secrets.randbits(53) == 0 produced u == -0.5 exactly → log(0).

    The fix uses rejection sampling: raw == 0 is rejected and retried; all
    other values produce a defined sample. Verify by scripting the RNG
    output sequence.
    """
    import sdsa.dp.laplace as L

    orig = L.secrets.randbits
    try:
        sequence = iter([0, 1, 0, (1 << 53) - 1, 1 << 52])
        def fake(_bits):
            try:
                return next(sequence)
            except StopIteration:
                return 1
        L.secrets.randbits = fake
        results = [L._laplace_sample(1.0) for _ in range(3)]
        # No crashes; no NaN values (NaN != NaN).
        assert all(isinstance(v, float) and v == v for v in results)
    finally:
        L.secrets.randbits = orig
