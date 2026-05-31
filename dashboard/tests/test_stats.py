"""Verify mathnet_percentile reproduces MathNet.Numerics .Percentile(95).

Reference values were produced by MathNet.Numerics 6.0.0-beta2 (the version
Sufni.Bridge ships) on the deterministic array
``x[i] = sin(i*0.7)*100 + i*0.13 + (i%17)*3.1``.
"""
import math

from app.telemetry.stats import mathnet_percentile


def _gen(n):
    return [math.sin(i * 0.7) * 100.0 + i * 0.13 + (i % 17) * 3.1 for i in range(n)]


def test_matches_mathnet_reference():
    reference = {
        5: 105.00497299884603,
        10: 105.00497299884603,
        11: 105.00497299884603,
        100: 137.06464013449693,
        159114: 19675.27644310718,
    }
    for n, want in reference.items():
        got = mathnet_percentile(_gen(n), 95)
        assert math.isclose(got, want, abs_tol=1e-9), f"n={n}: {got} != {want}"


def test_edges():
    assert math.isnan(mathnet_percentile([], 95))
    assert mathnet_percentile([42.0], 95) == 42.0
    assert mathnet_percentile([1.0, 2.0, 3.0], 0) == 1.0
    assert mathnet_percentile([1.0, 2.0, 3.0], 100) == 3.0
