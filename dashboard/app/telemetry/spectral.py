"""Shared spectral primitives, ported from Sufni.Bridge's TelemetryData.cs.

These mirror the C# implementations bit-for-bit (Welch's method with a symmetric
Hann window, 50% overlap, ``2/winSum**2`` single-sided power scaling) so that the
dashboard's spectrum/balance analysis matches the app on the same ``.psst`` blob.

References (Sufni.Bridge/.../Models/Telemetry/TelemetryData.cs):
  - ComputeWelchSpectrum        -> welch_spectrum
  - ComputeWelchCrossSpectrum   -> welch_cross_spectrum
  - IntegrateBand               -> integrate_band
  - MeanCoherence               -> mean_coherence
  - FrequencySplitFor           -> frequency_split_for
  - FindDominantPeak            -> find_dominant_peak

The C# uses MathNet's ``Window.Hann(width)`` which is the *symmetric* Hann window
``0.5 - 0.5*cos(2*pi*i/(width-1))`` — identical to ``numpy.hanning``. The forward
FFT is unnormalized (``FourierOptions.NoScaling``), matching ``numpy.fft.fft``.
"""

import math

import numpy as np


# ---------------------------------------------------------------------------
# Welch spectrum / cross-spectrum
# ---------------------------------------------------------------------------

def _clamp_seg_len(n: int, seg_len: int) -> int:
    """Mirror C# segLen clamping: cap at n, force even, reject below 64."""
    if seg_len > n:
        seg_len = n
    if (seg_len & 1) != 0:
        seg_len -= 1
    if seg_len < 64:
        return 0
    return seg_len


def welch_spectrum(signal, fs: int, seg_len: int = 8192):
    """Single-sided amplitude spectrum via Welch's method.

    Returns ``(freqs, amps)`` where ``amps = sqrt(Pxx)`` is the single-sided
    amplitude in the same unit as ``signal`` (mm for travel). Empty arrays when
    the signal is too short. Mirrors ``ComputeWelchSpectrum`` (TelemetryData.cs).
    """
    if signal is None or fs <= 0:
        return np.array([]), np.array([])

    sig = np.asarray(signal, dtype=np.float64)
    n = sig.size
    seg_len = _clamp_seg_len(n, seg_len)
    if seg_len == 0:
        return np.array([]), np.array([])

    window = np.hanning(seg_len)
    win_sum = window.sum()

    step = seg_len // 2
    bins = seg_len // 2
    avg_power = np.zeros(bins)
    seg_count = 0

    for start in range(0, n - seg_len + 1, step):
        seg = sig[start:start + seg_len]
        seg = (seg - seg.mean()) * window
        spec = np.fft.fft(seg)
        mag = np.abs(spec[:bins])
        avg_power += mag * mag
        seg_count += 1

    if seg_count == 0:
        return np.array([]), np.array([])

    power_scale = 2.0 / (win_sum * win_sum)
    d_f = fs / seg_len
    freqs = np.arange(bins) * d_f
    amps = np.sqrt(avg_power / seg_count * power_scale)
    return freqs, amps


def welch_cross_spectrum(x, y, fs: int, seg_len: int = 8192):
    """Welch cross-spectrum + per-axis auto-spectra in one pass.

    Returns ``(freqs, pxx, pyy, pxy)`` with single-sided power (pxx/pyy real,
    pxy complex). Empty arrays if the signals are too short or mismatched.
    Mirrors ``ComputeWelchCrossSpectrum`` (TelemetryData.cs).
    """
    if x is None or y is None or fs <= 0:
        return np.array([]), np.array([]), np.array([]), np.array([])

    xs = np.asarray(x, dtype=np.float64)
    ys = np.asarray(y, dtype=np.float64)
    if xs.size != ys.size:
        return np.array([]), np.array([]), np.array([]), np.array([])

    n = xs.size
    seg_len = _clamp_seg_len(n, seg_len)
    if seg_len == 0:
        return np.array([]), np.array([]), np.array([]), np.array([])

    window = np.hanning(seg_len)
    win_sum = window.sum()

    step = seg_len // 2
    bins = seg_len // 2
    pxx = np.zeros(bins)
    pyy = np.zeros(bins)
    pxy = np.zeros(bins, dtype=np.complex128)
    seg_count = 0

    for start in range(0, n - seg_len + 1, step):
        sx = (xs[start:start + seg_len] - xs[start:start + seg_len].mean()) * window
        sy = (ys[start:start + seg_len] - ys[start:start + seg_len].mean()) * window
        fx = np.fft.fft(sx)[:bins]
        fy = np.fft.fft(sy)[:bins]
        pxx += np.abs(fx) ** 2
        pyy += np.abs(fy) ** 2
        pxy += fx * np.conjugate(fy)
        seg_count += 1

    if seg_count == 0:
        return np.array([]), np.array([]), np.array([]), np.array([])

    power_scale = 2.0 / (win_sum * win_sum)
    d_f = fs / seg_len
    freqs = np.arange(bins) * d_f
    pxx = pxx / seg_count * power_scale
    pyy = pyy / seg_count * power_scale
    pxy = pxy / seg_count * power_scale
    return freqs, pxx, pyy, pxy


# ---------------------------------------------------------------------------
# Band integration / coherence
# ---------------------------------------------------------------------------

def integrate_band(freqs, spectrum, f_low: float, f_high: float) -> float:
    """Trapezoidal integral of a single-sided spectrum over [f_low, f_high].

    Mirrors ``IntegrateBand`` (TelemetryData.cs), including the per-edge linear
    interpolation of the spectrum at the band boundaries.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    spectrum = np.asarray(spectrum, dtype=np.float64)
    if freqs.size < 2 or spectrum.size != freqs.size:
        return 0.0

    total = 0.0
    for i in range(1, freqs.size):
        f0, f1 = freqs[i - 1], freqs[i]
        if f1 < f_low or f0 > f_high:
            continue
        a = max(f0, f_low)
        b = min(f1, f_high)
        if b <= a:
            continue
        s0 = spectrum[i - 1] + (spectrum[i] - spectrum[i - 1]) * (a - f0) / (f1 - f0)
        s1 = spectrum[i - 1] + (spectrum[i] - spectrum[i - 1]) * (b - f0) / (f1 - f0)
        total += 0.5 * (s0 + s1) * (b - a)
    return total


def mean_coherence(freqs, pxx, pyy, pxy, f_low: float, f_high: float):
    """Mean magnitude-squared coherence gamma^2 over [f_low, f_high].

    gamma^2(f) = |Pxy|^2 / (Pxx*Pyy), clipped to <= 1, DC bin skipped. Returns
    ``None`` when no bins qualify. Mirrors ``MeanCoherence`` (TelemetryData.cs).
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    if freqs.size == 0 or len(pxy) != freqs.size:
        return None

    total = 0.0
    count = 0
    for k in range(1, freqs.size):
        f = freqs[k]
        if f < f_low or f > f_high:
            continue
        denom = pxx[k] * pyy[k]
        if denom <= 1e-30:
            continue
        mag2 = pxy[k].real * pxy[k].real + pxy[k].imag * pxy[k].imag
        g2 = mag2 / denom
        if g2 > 1.0:
            g2 = 1.0
        total += g2
        count += 1
    return total / count if count > 0 else None


# ---------------------------------------------------------------------------
# Discipline split / peak detection
# ---------------------------------------------------------------------------

def frequency_split_for(discipline) -> float:
    """Discipline-aware Low/Mid split frequency (Hz).

    Mirrors ``FrequencySplitFor``: XC -> 2.8, Downhill -> 1.6, else 2.0.
    Accepts a string (``xc``/``enduro``/``downhill``), ``None`` or an int code
    (0=XC, 1=Enduro, 2=Downhill).
    """
    key = _normalize_discipline(discipline)
    if key == 'xc':
        return 2.8
    if key == 'downhill':
        return 1.6
    return 2.0  # Enduro / default / None


def _normalize_discipline(discipline):
    if discipline is None:
        return 'enduro'
    if isinstance(discipline, str):
        return discipline.strip().lower()
    # Numeric Discipline enum: 0=XC, 1=Enduro, 2=Downhill
    return {0: 'xc', 1: 'enduro', 2: 'downhill'}.get(int(discipline), 'enduro')


def find_dominant_peak(freqs, amps, f_min: float, f_max: float):
    """Body-resonance peak detection in the velocity domain.

    The travel-amplitude spectrum is multiplied by ``2*pi*f`` to remove its
    1/f-like trend; the absolute max of that velocity spectrum within
    ``[f_min, f_max]`` is the body resonance. Quadratic (parabolic) sub-bin
    interpolation in the velocity-dB domain recovers scalloping loss. Returns
    ``(freq, travel_amp)`` so plot markers sit on the travel curve.

    Mirrors ``FindDominantPeak`` (TelemetryData.cs).
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    amps = np.asarray(amps, dtype=np.float64)
    n = amps.size
    if n < 2:
        return float('nan'), 0.0

    best_k = -1
    best_vel = 0.0
    for i in range(1, n):
        f = freqs[i]
        if f < f_min or f > f_max:
            continue
        vel = amps[i] * 2.0 * math.pi * f
        if vel > best_vel:
            best_vel = vel
            best_k = i

    if best_k < 0:
        return float('nan'), 0.0

    best_f = freqs[best_k]
    best_a = amps[best_k]

    # Quadratic peak interpolation in velocity-dB domain.
    if 0 < best_k < n - 1:
        v0 = amps[best_k - 1] * 2.0 * math.pi * freqs[best_k - 1]
        v1 = best_vel
        v2 = amps[best_k + 1] * 2.0 * math.pi * freqs[best_k + 1]
        if v0 > 0 and v1 > 0 and v2 > 0:
            alpha = 20.0 * math.log10(v0)
            beta = 20.0 * math.log10(v1)
            gamma = 20.0 * math.log10(v2)
            denom = alpha - 2.0 * beta + gamma
            if denom < 0:  # parabola opens downward -> true local max
                delta = 0.5 * (alpha - gamma) / denom
                if -0.5 < delta < 0.5:
                    d_f = freqs[best_k + 1] - freqs[best_k]
                    best_f = freqs[best_k] + delta * d_f
                    peak_vel_db = beta - 0.25 * (alpha - gamma) * delta
                    peak_vel = 10.0 ** (peak_vel_db / 20.0)
                    best_a = peak_vel / (2.0 * math.pi * best_f)

    return best_f, best_a
