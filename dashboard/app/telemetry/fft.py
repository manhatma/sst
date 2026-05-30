"""Wheel-travel spectrum, ported from Sufni.Bridge's CombinedTravelFftPlot.cs.

Replaces the old crude single-``rfft`` over a zero-padded 20000-pt window with
Welch's method (``spectral.welch_spectrum``) rendered on log-log axes:

  * X axis: frequency in Hz, logarithmic.
  * Y axis: amplitude in dB re 0.01 mm (``20*log10(amp / 0.01mm)``), floored at
    ``-40 dB``.
  * A body-resonance peak marker (open circle + dashed guide + label) located in
    the 1.3-4.5 Hz band via the velocity-domain ``find_dominant_peak``.

The per-suspension figures keep their ``f_fft`` / ``r_fft`` column slots and the
``ds_fft`` / ``b_fft`` model names so the live box-select recompute path
(``update_fft`` -> ``SST.update.fft``) keeps working with the new data shape
``{freqs, db}`` (peak markers stay static, consistent with the rest of the
cache-time plots).
"""

import math

import numpy as np
from bokeh.models import HoverTool, Label, Span, WheelZoomTool
from bokeh.models.ranges import Range1d
from bokeh.models.sources import ColumnDataSource
from bokeh.plotting import figure

from app.telemetry.spectral import find_dominant_peak, welch_spectrum

TRAVEL_REFERENCE_MM = 0.01
FLOOR_DB = -40.0
# Display window (Hz). Below DISPLAY_MIN_HZ is DC/drift. DISPLAY_MAX_HZ matches
# CombinedTravelFftPlot.cs's default (100 Hz) — well within Nyquist at 860 SPS
# (430 Hz); the per-session value is still clamped to Nyquist as a safety net.
DISPLAY_MIN_HZ = 0.3
DISPLAY_MAX_HZ = 100.0
# Body-resonance search band, matching CalculateBalanceMetrics' peak detection.
PEAK_MIN_HZ = 1.3
PEAK_MAX_HZ = 4.5


def _to_db(amp: float) -> float:
    if amp <= 0:
        return FLOOR_DB
    return max(20.0 * math.log10(amp / TRAVEL_REFERENCE_MM), FLOOR_DB)


def _spectrum_curve(travel, sample_rate: int, max_hz: float):
    """Return ``(dict(freqs, db), freqs_full, amps_full)`` for a travel signal.

    ``freqs``/``db`` are the display arrays (DC skipped, range-limited, dB);
    the full Welch arrays are returned alongside for peak detection.
    """
    freqs, amps = welch_spectrum(travel, sample_rate)
    xs, ys = [], []
    if freqs.size:
        for i in range(1, freqs.size):
            f = float(freqs[i])
            if f < DISPLAY_MIN_HZ:
                continue
            if f > max_hz:
                break
            xs.append(f)
            ys.append(_to_db(float(amps[i])))
    return dict(freqs=xs, db=ys), freqs, amps


def _display_max_hz(sample_rate: int) -> float:
    nyquist = sample_rate / 2.0 if sample_rate else DISPLAY_MAX_HZ
    return min(DISPLAY_MAX_HZ, nyquist * 0.999)


def _y_limits(*db_lists):
    vals = [v for lst in db_lists for v in lst if np.isfinite(v)]
    if not vals:
        return FLOOR_DB, 0.0
    y_min = math.floor(min(vals) / 10.0) * 10.0
    y_top = max(vals) + 8.0
    if y_top - y_min < 20.0:
        y_top = y_min + 20.0
    return y_min, y_top


def _add_peak_marker(p, freqs, amps, color, y_top):
    """Open-circle marker + dashed vertical guide + label at the body peak."""
    if freqs is None or len(freqs) == 0:
        return
    peak_f, peak_a = find_dominant_peak(freqs, amps, PEAK_MIN_HZ, PEAK_MAX_HZ)
    if not np.isfinite(peak_f) or peak_a <= 0:
        return
    peak_db = _to_db(peak_a)
    p.scatter([peak_f], [peak_db], marker='circle', size=10,
              line_color=color, line_width=2, fill_color=None)
    p.add_layout(Span(location=peak_f, dimension='height',
                      line_color=color, line_dash='dashed', line_width=1))
    p.add_layout(Label(x=peak_f, y=y_top, y_offset=-6,
                       text=f"{peak_f:.2f} Hz", text_color=color,
                       text_font_size='10pt', text_align='center',
                       text_baseline='top', angle=math.pi / 2.0))


def _base_spectrum_figure(title: str, max_hz: float, y_range) -> figure:
    p = figure(
        title=title,
        min_height=150,
        min_border_left=70,
        min_border_right=50,
        sizing_mode='stretch_both',
        toolbar_location='above',
        tools='xpan,reset',
        active_drag='xpan',
        x_axis_type='log',
        x_axis_label="Frequency (Hz)",
        y_axis_label="Amplitude (dB re 0.01 mm)",
        x_range=Range1d(DISPLAY_MIN_HZ, max_hz),
        y_range=Range1d(*y_range),
        output_backend='webgl')
    p.add_tools(WheelZoomTool(maintain_focus=False, dimensions='width'))
    return p


def fft_figure(travel: list[float], sample_rate: int, color, title: str) -> figure:
    max_hz = _display_max_hz(sample_rate)
    data, freqs, amps = _spectrum_curve(travel, sample_rate, max_hz)
    source = ColumnDataSource(name='ds_fft', data=data)

    y_range = _y_limits(data['db'])
    p = _base_spectrum_figure(title, max_hz, y_range)
    p.add_tools(HoverTool(name='ht', tooltips=[("freq", "@freqs{0.00} Hz"),
                                               ("amp", "@db{0.0} dB")],
                          mode='vline', attachment='above'))
    p.line(name='b_fft', x='freqs', y='db', source=source,
           line_width=2, color=color)
    _add_peak_marker(p, freqs, amps, color, y_range[1])
    return p


def fft_comparison_figure(front_travel: list[float], rear_travel: list[float],
                          sample_rate: int, front_color, rear_color) -> figure:
    max_hz = _display_max_hz(sample_rate)
    front_data, f_freqs, f_amps = _spectrum_curve(front_travel, sample_rate, max_hz)
    rear_data, r_freqs, r_amps = _spectrum_curve(rear_travel, sample_rate, max_hz)
    front_source = ColumnDataSource(name='ds_fft_front_comp', data=front_data)
    rear_source = ColumnDataSource(name='ds_fft_rear_comp', data=rear_data)

    y_range = _y_limits(front_data['db'], rear_data['db'])
    p = _base_spectrum_figure("Frequency comparison", max_hz, y_range)
    p.line(x='freqs', y='db', source=front_source, line_width=2,
           color=front_color, legend_label='Front')
    p.line(x='freqs', y='db', source=rear_source, line_width=2,
           color=rear_color, legend_label='Rear')
    _add_peak_marker(p, f_freqs, f_amps, front_color, y_range[1])
    _add_peak_marker(p, r_freqs, r_amps, rear_color, y_range[1])
    if p.legend:
        p.legend.location = 'top_right'
        p.legend.click_policy = 'hide'
    return p


def update_fft(travel: list[float], sample_rate: int):
    """Box-select recompute payload — refreshes the curve (peak stays static)."""
    max_hz = _display_max_hz(sample_rate)
    data, _, _ = _spectrum_curve(travel, sample_rate, max_hz)
    return dict(data=data)
