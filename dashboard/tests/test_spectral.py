"""Unit tests for the spectral primitives (app/telemetry/spectral.py).

Pure numpy — no Flask/DB — so they run independently of the API test harness.
Reference values follow the C# ``2/winSum**2`` single-sided convention where
``amps = sqrt(Pxx)`` is the RMS single-sided amplitude (A/sqrt(2) for a sine of
amplitude A on a bin centre).
"""
import math

import numpy as np
import pytest

from app.telemetry import spectral as sp


def _sine(fs, n, amp, freq):
    t = np.arange(n) / fs
    return amp * np.sin(2 * np.pi * freq * t)


def test_welch_spectrum_on_bin_amplitude():
    # fs=1024, segLen=8192 -> dF=0.125; freq 2.0 Hz lands on bin k=16.
    fs, n, amp, freq = 1024, 32768, 4.0, 2.0
    freqs, amps = sp.welch_spectrum(_sine(fs, n, amp, freq), fs)
    assert freqs.size == 4096          # segLen/2 bins
    assert math.isclose(float(freqs[1] - freqs[0]), fs / 8192, rel_tol=1e-9)
    k = int(amps.argmax())
    assert math.isclose(float(freqs[k]), freq, abs_tol=0.13)
    # RMS single-sided amplitude == A / sqrt(2).
    assert math.isclose(float(amps[k]), amp / math.sqrt(2), rel_tol=0.02)


def test_welch_spectrum_too_short_returns_empty():
    freqs, amps = sp.welch_spectrum(np.zeros(32), 1000)
    assert freqs.size == 0 and amps.size == 0


def test_find_dominant_peak_recovers_frequency_and_amplitude():
    fs, n, amp, freq = 1000, 32768, 4.0, 1.5
    freqs, amps = sp.welch_spectrum(_sine(fs, n, amp, freq), fs)
    f, a = sp.find_dominant_peak(freqs, amps, 1.0, 3.0)
    # Parabolic interpolation corrects scalloping toward the true values.
    assert math.isclose(f, freq, abs_tol=0.05)
    assert math.isclose(a, amp / math.sqrt(2), rel_tol=0.05)


def test_find_dominant_peak_empty_band_returns_nan():
    # A band entirely above Nyquist contains no bins -> NaN (mirrors C#: a peak
    # is reported wherever any in-band bin exists, so use an out-of-range band).
    fs, n = 1000, 32768
    freqs, amps = sp.welch_spectrum(_sine(fs, n, 4.0, 1.5), fs)
    f, a = sp.find_dominant_peak(freqs, amps, 600.0, 700.0)
    assert math.isnan(f) and a == 0.0


def test_coherence_identical_signals_is_one():
    fs, n = 1000, 32768
    x = _sine(fs, n, 3.0, 2.0) + 0.5 * _sine(fs, n, 1.0, 5.0)
    cf, pxx, pyy, pxy = sp.welch_cross_spectrum(x, x, fs)
    coh = sp.mean_coherence(cf, pxx, pyy, pxy, 1.0, 8.0)
    assert math.isclose(coh, 1.0, abs_tol=1e-9)


def test_coherence_uncorrelated_signals_is_low():
    rng = np.random.default_rng(42)
    fs, n = 1000, 65536
    x = rng.standard_normal(n)
    y = rng.standard_normal(n)
    cf, pxx, pyy, pxy = sp.welch_cross_spectrum(x, y, fs)
    coh = sp.mean_coherence(cf, pxx, pyy, pxy, 5.0, 50.0)
    assert coh < 0.2


def test_integrate_band_trapezoid():
    freqs = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    spectrum = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    assert math.isclose(sp.integrate_band(freqs, spectrum, 1.0, 3.0), 2.0)
    # Partial edge interpolation.
    ramp = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    assert math.isclose(sp.integrate_band(freqs, ramp, 0.0, 4.0), 8.0)


@pytest.mark.parametrize("disc,expected", [
    ('xc', 2.8), ('enduro', 2.0), ('downhill', 1.6), (None, 2.0),
    (0, 2.8), (1, 2.0), (2, 1.6), ('XC', 2.8),
])
def test_frequency_split_for(disc, expected):
    assert sp.frequency_split_for(disc) == expected
