"""Phase-portrait, acceleration and front/rear-scatter plots (the "Misc" tab).

Ported from Sufni.Bridge:
  - PositionVelocityPlot.cs            -> position_velocity_figure (fork / damper)
  - PositionVelocityComparisonPlot.cs  -> position_velocity_comparison_figure
  - AccelerationTimeCroppedPlot.cs     -> acceleration_figure
  - FrontRearTravelScatterPlot.cs      -> front_rear_scatter_figure

The phase portraits reconstruct travel-vs-velocity traces from the per-stroke
windows (compressions + rebounds, ordered by start, with NaN breaks across large
gaps — ``PhasePortraitStrokeGapThreshold = 10``). The rear/damper domain converts
wheel velocity through the linkage polynomial derivative (leverage), exactly like
``CalculateDamperPositionVelocityData``. Traces are stride-downsampled for a
reasonable embedded-payload size; statistics are computed on full resolution.
"""

import math

import numpy as np
from bokeh.models import ColumnDataSource, Label, Span
from bokeh.models.ranges import Range1d
from bokeh.models.tickers import FixedTicker
from bokeh.plotting import figure

from app.telemetry.filters import acceleration_smoother

GRAVITY_MM_PER_S2 = 9806.65
STROKE_GAP_THRESHOLD = 10        # PhasePortraitStrokeGapThreshold
# Downsample target for the embedded phase-portrait / acceleration traces. The
# whole document is serialised into the page, so these are kept modest; the
# trace shape and (full-resolution) acceleration statistics are preserved.
MAX_TRACE_POINTS = 8000
GROUND = '#dddddd'
TREND_COLOR = '#e5df12'


# ---------------------------------------------------------------------------
# Stroke helpers
# ---------------------------------------------------------------------------

def _ordered_strokes(suspension):
    strokes = list(suspension.Strokes.Compressions or []) + \
              list(suspension.Strokes.Rebounds or [])
    strokes.sort(key=lambda s: s.Start)
    return strokes


def _trace_stride(suspension, arr_len):
    total = 0
    for s in _ordered_strokes(suspension):
        if s.End < s.Start or s.Start < 0 or s.End >= arr_len:
            continue
        total += s.End - s.Start + 1
    return max(1, total // MAX_TRACE_POINTS)


def _phase_trace(suspension, travel_values, velocity_values, arr_len, stride):
    """Assemble (travel, velocity) trace arrays with NaN breaks across gaps."""
    segs_t, segs_v = [], []
    last_end = None
    for s in _ordered_strokes(suspension):
        if s.End < s.Start or s.Start < 0 or s.End >= arr_len:
            continue
        if last_end is not None and s.Start - last_end > STROKE_GAP_THRESHOLD:
            segs_t.append(np.array([np.nan]))
            segs_v.append(np.array([np.nan]))
        segs_t.append(travel_values[s.Start:s.End + 1:stride])
        segs_v.append(velocity_values[s.Start:s.End + 1:stride])
        last_end = s.End
    if not segs_t:
        return np.array([]), np.array([])
    return np.concatenate(segs_t), np.concatenate(segs_v)


def _velocity_limits(velocity):
    """Asymmetric Y padding rounded up to the nearest 500 mm/s (min 500)."""
    finite = velocity[np.isfinite(velocity)] if velocity.size else velocity
    pos = finite[finite > 0]
    neg = finite[finite < 0]
    v_pos = float(pos.max()) if pos.size else 0.0
    v_neg = float(np.abs(neg).max()) if neg.size else 0.0
    top = max(math.ceil(v_pos * 1.1 / 500.0) * 500.0, 500.0)
    bottom = max(math.ceil(v_neg * 1.1 / 500.0) * 500.0, 500.0)
    return -bottom, top


def _phase_figure(title, x_label, y_label, max_travel):
    p = figure(
        name='phase',
        title=title,
        min_height=320,
        min_border_left=70,
        sizing_mode='stretch_both',
        toolbar_location='above',
        tools='pan,box_zoom,wheel_zoom,reset',
        active_drag='pan',
        x_axis_label=x_label,
        y_axis_label=y_label,
        x_range=Range1d(0, max_travel if max_travel and max_travel > 0 else 1.0),
        output_backend='webgl')
    return p


# ---------------------------------------------------------------------------
# Phase portraits
# ---------------------------------------------------------------------------

def position_velocity_figure(telemetry, suspension_type, color):
    """Fork-domain (front) or damper-domain (rear) position-velocity portrait."""
    is_front = suspension_type == 'front'
    suspension = telemetry.Front if is_front else telemetry.Rear
    linkage = telemetry.Linkage
    arr_len = min(len(suspension.Travel or []), len(suspension.Velocity or []))
    travel_arr = np.asarray(suspension.Travel or [], dtype=np.float64)
    vel_arr = np.asarray(suspension.Velocity or [], dtype=np.float64)
    stride = _trace_stride(suspension, arr_len)

    if is_front:
        sin_ha = math.sin(linkage.HeadAngle * math.pi / 180.0)
        scale = (1.0 / sin_ha) if sin_ha > 0 else 0.0
        t_vals = travel_arr * scale
        v_vals = vel_arr * scale
        max_travel = linkage.MaxFrontStroke or 0
        title = "Fork position vs. velocity"
        x_label, y_label = "Fork travel (mm)", "Fork velocity (mm/s)"
        label = "Front"
    else:
        shock_pos_full, leverage_full = _damper_shock_leverage(linkage, travel_arr)
        t_vals = shock_pos_full
        with np.errstate(divide='ignore', invalid='ignore'):
            v_vals = np.where(leverage_full > 0, vel_arr / leverage_full, 0.0)
        max_travel = linkage.MaxRearStroke or 0
        title = "Damper position vs velocity"
        x_label, y_label = "Damper travel (mm)", "Damper velocity (mm/s)"
        label = "Rear"

    travel, velocity = _phase_trace(suspension, t_vals, v_vals, arr_len, stride)
    y_bottom, y_top = _velocity_limits(velocity)

    p = _phase_figure(title, x_label, y_label, max_travel)
    p.y_range = Range1d(y_bottom, y_top)
    p.add_layout(Span(location=0, dimension='width',
                      line_color=GROUND, line_dash='dotted', line_width=1))
    if travel.size:
        src = ColumnDataSource(data=dict(t=travel.tolist(), v=velocity.tolist()))
        p.line('t', 'v', source=src, line_width=1, color=color, line_alpha=0.9)
    p.add_layout(Label(x=max_travel, y=y_top * 0.95, text=label, text_color=color,
                       text_font_size='12px', text_align='right', x_offset=-6))
    return p


def _damper_shock_leverage(linkage, wheel_travel):
    """Vectorised WheelToDamperTravel + leverage (dWheel/dShock) for each sample.

    Mirrors ``CalculateDamperPositionVelocityData``: a 3rd-order shock->wheel
    polynomial (``ShockWheelCoeffs``), inverted to shock travel and differentiated
    to leverage. The C# inverts per-sample via 50-step binary search; we build a
    dense monotonic shock->wheel grid and invert with ``np.interp`` (equivalent to
    interpolation precision).
    """
    coeffs = np.asarray(linkage.ShockWheelCoeffs or [], dtype=np.float64)
    max_shock = linkage.MaxRearStroke or 0
    if coeffs.size == 0 or max_shock <= 0:
        zeros = np.zeros_like(wheel_travel)
        return zeros, np.ones_like(wheel_travel)
    poly = np.poly1d(np.flip(coeffs))     # wheel = poly(shock)
    dpoly = poly.deriv()                   # leverage = dWheel/dShock
    shock_grid = np.linspace(0.0, max_shock, 4000)
    wheel_grid = np.maximum.accumulate(poly(shock_grid))  # enforce monotonic xp
    shock_pos = np.clip(np.interp(wheel_travel, wheel_grid, shock_grid),
                        0.0, max_shock)
    leverage = dpoly(shock_pos)
    return shock_pos, leverage


def position_velocity_comparison_figure(telemetry, front_color, rear_color):
    """Front + rear wheel-domain portraits overlaid (rear drawn first)."""
    linkage = telemetry.Linkage
    max_travel = max(linkage.MaxFrontTravel or 0, linkage.MaxRearTravel or 0)
    p = _phase_figure("Position vs velocity comparison",
                      "Wheel travel (mm)", "Velocity (mm/s)", max_travel)
    p.add_layout(Span(location=0, dimension='width',
                      line_color=GROUND, line_dash='dotted', line_width=1))

    all_v = []

    def add(suspension, color):
        arr_len = min(len(suspension.Travel or []), len(suspension.Velocity or []))
        if arr_len == 0:
            return
        stride = _trace_stride(suspension, arr_len)
        t = np.asarray(suspension.Travel, dtype=np.float64)
        v = np.asarray(suspension.Velocity, dtype=np.float64)
        travel, velocity = _phase_trace(suspension, t, v, arr_len, stride)
        if travel.size:
            src = ColumnDataSource(data=dict(t=travel.tolist(), v=velocity.tolist()))
            p.line('t', 'v', source=src, line_width=1, color=color, line_alpha=0.6)
            all_v.append(velocity)

    if telemetry.Rear.Present:
        add(telemetry.Rear, rear_color)
    if telemetry.Front.Present:
        add(telemetry.Front, front_color)

    combined = np.concatenate(all_v) if all_v else np.array([])
    y_bottom, y_top = _velocity_limits(combined)
    p.y_range = Range1d(y_bottom, y_top)
    if telemetry.Front.Present:
        p.add_layout(Label(x=max_travel, y=y_top * 0.95, text="Front",
                           text_color=front_color, text_font_size='12px',
                           text_align='right', x_offset=-6))
    if telemetry.Rear.Present:
        p.add_layout(Label(x=max_travel, y=y_top * 0.87, text="Rear",
                           text_color=rear_color, text_font_size='12px',
                           text_align='right', x_offset=-6))
    return p


# ---------------------------------------------------------------------------
# Acceleration
# ---------------------------------------------------------------------------

def acceleration_figure(suspension, sample_rate, color, title, label):
    """Acceleration (g) over time: 2nd derivative of WH-presmoothed velocity."""
    v = np.asarray(suspension.Velocity or [], dtype=np.float64)
    p = figure(
        name='accel',
        title=title,
        min_height=260,
        min_border_left=60,
        sizing_mode='stretch_both',
        toolbar_location='above',
        tools='xpan,xwheel_zoom,reset',
        active_drag='xpan',
        x_axis_label="Time (s)",
        y_axis_label="Acceleration (g)",
        output_backend='webgl')

    if v.size < 2 or sample_rate <= 0:
        return p

    vs = acceleration_smoother().smooth(v)
    accel = np.empty_like(vs)
    accel[0] = (vs[1] - vs[0]) * sample_rate / GRAVITY_MM_PER_S2
    accel[1:-1] = (vs[2:] - vs[:-2]) * sample_rate / 2.0 / GRAVITY_MM_PER_S2
    accel[-1] = (vs[-1] - vs[-2]) * sample_rate / GRAVITY_MM_PER_S2

    a_max = float(accel.max())
    a_min = float(accel.min())
    a_rms = float(np.sqrt(np.mean(accel * accel)))

    # Downsample for display (stats already computed on full resolution).
    stride = max(1, accel.size // MAX_TRACE_POINTS)
    idx = np.arange(0, accel.size, stride)
    t = idx / sample_rate
    src = ColumnDataSource(data=dict(t=t.tolist(), a=accel[idx].tolist()))

    span = max(a_max - a_min, 1e-9)
    p.x_range = Range1d(0, accel.size / sample_rate)
    p.y_range = Range1d(a_min - span * 0.05, a_max + span * 0.05)
    p.add_layout(Span(location=0, dimension='width',
                      line_color=GROUND, line_dash='dotted', line_width=1))
    p.line('t', 'a', source=src, line_width=1, color=color)
    p.add_layout(Label(x=0, y=a_max + span * 0.05, text=label, text_color=color,
                       text_font_size='12px', text_align='left',
                       x_offset=6, y_offset=4))
    stats = f"max: {a_max:7.3f}\nmin: {a_min:7.3f}\nrms: {a_rms:7.3f}"
    p.add_layout(Label(x=accel.size / sample_rate, y=a_max + span * 0.05,
                       text=stats, text_color=TREND_COLOR, text_font='monospace',
                       text_font_size='9px', text_align='right',
                       text_baseline='top', x_offset=-10, y_offset=6,
                       background_fill_color='#15191C', background_fill_alpha=0.86,
                       border_line_color=TREND_COLOR, border_line_alpha=0.3))
    return p


# ---------------------------------------------------------------------------
# Front/rear travel scatter
# ---------------------------------------------------------------------------

def front_rear_scatter_figure(telemetry, rear_color):
    """Rear% vs front% travel phase portrait + slope-through-origin + 1:1 line."""
    linkage = telemetry.Linkage
    fr = np.asarray(telemetry.Front.Travel or [], dtype=np.float64)
    rr = np.asarray(telemetry.Rear.Travel or [], dtype=np.float64)
    count = min(fr.size, rr.size)

    p = figure(
        name='fr_scatter',
        title="Front vs rear travel",
        min_height=320,
        match_aspect=True,
        sizing_mode='stretch_both',
        toolbar_location='above',
        tools='pan,box_zoom,wheel_zoom,reset',
        active_drag='pan',
        x_axis_label="Rear suspension travel (%)",
        y_axis_label="Front suspension travel (%)",
        x_range=Range1d(0, 100),
        y_range=Range1d(0, 100),
        output_backend='webgl')
    ticks = list(range(0, 101, 10))
    p.xaxis.ticker = FixedTicker(ticks=ticks)
    p.yaxis.ticker = FixedTicker(ticks=ticks)

    if count == 0 or (linkage.MaxFrontTravel or 0) == 0 or (linkage.MaxRearTravel or 0) == 0:
        return p

    max_scatter = 12000
    stride = count // max_scatter if count > max_scatter else 1
    idx = np.arange(0, count, stride)
    rear = rr[idx] / linkage.MaxRearTravel * 100.0
    front = fr[idx] / linkage.MaxFrontTravel * 100.0

    p.scatter(rear.tolist(), front.tolist(), size=2,
              fill_color='#d8d8d8', line_color=None, fill_alpha=0.4)
    # 1:1 reference (dashed) and slope-through-origin trend.
    p.line([0, 100], [0, 100], line_color=rear_color, line_width=2, line_dash='dashed')
    denom = float(np.sum(rear * rear))
    if denom > 0:
        slope = float(np.sum(rear * front) / denom)
        p.line([0, 100], [0, 100 * slope], line_color=TREND_COLOR, line_width=2)
        p.add_layout(Label(x=100, y=0, text=f"a={slope:.2f}", text_color=TREND_COLOR,
                           text_font_size='12px', text_align='right',
                           text_baseline='bottom', x_offset=-10, y_offset=10))
    return p
