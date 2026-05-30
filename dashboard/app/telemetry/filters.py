"""Signal filters ported from Sufni.Bridge (Models/Telemetry/Filters.cs).

The Whittaker-Henderson smoother solves the penalised least-squares system

    (I + lambda * D'D) x = y

where ``D`` is the order-th finite-difference operator. This is the same system
the C# ``WhittakerHendersonSmoother`` builds and solves via banded Cholesky; here
we assemble the sparse banded matrix and solve it with SciPy, which is
numerically equivalent.

The dashboard only needs the acceleration pre-smoother (order 3, lambda 10000 —
see ``Parameters.WhAccelOrder``/``WhAccelLambda``). gosst already applies the
velocity-tuned WH (order 3, lambda 11) when it derives ``Velocity`` from
``Travel``, so that one is not re-done here.
"""

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

# Mirror of TelemetryData.cs / Parameters.cs.
WH_ACCEL_ORDER = 3
WH_ACCEL_LAMBDA = 10000.0

# order-th forward-difference stencils (DiffCoeffs in Filters.cs).
_DIFF_COEFFS = {
    1: [-1, 1],
    2: [1, -2, 1],
    3: [-1, 3, -3, 1],
    4: [1, -4, 6, -4, 1],
    5: [-1, 5, -10, 10, -5, 1],
}


class WhittakerHendersonSmoother:
    """Penalised least-squares smoother, banded direct solve.

    Mirrors ``WhittakerHendersonSmoother`` (Filters.cs). The factorisation is
    cached per signal length so repeated ``smooth`` calls on equal-length arrays
    reuse the LU decomposition, matching the C# matrix cache.
    """

    def __init__(self, order: int, lam: float):
        if order not in _DIFF_COEFFS:
            raise ValueError(f"Order must be between 1 and {len(_DIFF_COEFFS)}")
        self.order = order
        self.lam = lam
        self._n = None
        self._lu = None

    def _factorize(self, n: int):
        coeffs = np.array(_DIFF_COEFFS[self.order], dtype=np.float64)
        rows = n - self.order
        if rows <= 0:
            # Too short to penalise — identity (no smoothing possible).
            self._lu = None
            self._n = n
            return
        # D: (n-order) x n banded difference operator.
        diagonals = [np.full(rows, c) for c in coeffs]
        offsets = list(range(self.order + 1))
        d = sparse.diags(diagonals, offsets, shape=(rows, n), format='csc')
        a = (sparse.identity(n, format='csc')
             + self.lam * (d.transpose() @ d)).tocsc()
        self._lu = splu(a)
        self._n = n

    def smooth(self, data):
        y = np.asarray(data, dtype=np.float64)
        n = y.size
        if n < 2:
            return y.copy()
        if self._n != n or self._lu is None:
            self._factorize(n)
        if self._lu is None:
            return y.copy()
        return self._lu.solve(y)


def acceleration_smoother() -> WhittakerHendersonSmoother:
    """Smoother used as a pre-filter for the acceleration plot (Phase 3)."""
    return WhittakerHendersonSmoother(WH_ACCEL_ORDER, WH_ACCEL_LAMBDA)
