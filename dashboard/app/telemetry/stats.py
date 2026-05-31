"""Statistics helpers matched to Sufni.Bridge's MathNet.Numerics behaviour.

``mathnet_percentile`` reproduces ``MathNet.Numerics.Statistics.Percentile`` /
``QuantileInplace`` exactly: the R-8 ("median-unbiased") estimator
``h = (n + 1/3)*tau + 1/3`` with linear interpolation between order statistics.
Verified bit-for-bit (12 significant digits) against MathNet 6.0.0-beta2 — the
version Sufni.Bridge ships — so dashboard travel statistics (dynamic SAG, 95th
percentile) match the app's Balance/Travel values. ``numpy.percentile``'s default
is R-7 (linear), which differs by up to a fraction of a percent.
"""

import math

import numpy as np


def mathnet_percentile(values, p: float) -> float:
    """MathNet.Numerics ``Percentile(p)`` — R-8 / median-unbiased estimator."""
    a = np.sort(np.asarray(values, dtype=np.float64))
    n = a.size
    if n == 0:
        return float('nan')
    tau = p / 100.0
    if tau <= 0.0 or n == 1:
        return float(a[0])
    if tau >= 1.0:
        return float(a[-1])
    h = (n + 1.0 / 3.0) * tau + 1.0 / 3.0
    hf = int(math.floor(h))
    lo = min(max(hf - 1, 0), n - 1)
    hi = min(max(hf, 0), n - 1)
    return float(a[lo] + (h - hf) * (a[hi] - a[lo]))
