"""Multi-session comparison plots, ported from Sufni.Bridge's Compare*.cs.

Each builder takes a list of ``CompareSession`` (telemetry + per-session colour +
name) and overlays them on shared axes with a per-session colour legend, mirroring
CompareTravelHistogramPlot / CompareVelocityHistogramPlot / CompareLowSpeedVelocityPlot
/ CompareSpectrumPlot / CompareBalancePlot / CompareFrontRearTravelPlot.

These figures are intentionally light — filled step polygons, normal-distribution
overlays, trend lines and downsampled log-log spectra — so a comparison of several
sessions stays a small embedded payload (no raw 159k travel/velocity arrays).

``build_comparison`` assembles every figure into one Bokeh document and returns
``(script, figures)`` for the on-demand ``/api/session/compare`` route.
"""

import math
from dataclasses import dataclass

import numpy as np
from bokeh.document import Document
from bokeh.embed import components
from bokeh.models import Label, Span
from bokeh.models.ranges import Range1d
from bokeh.models.tickers import FixedTicker
from bokeh.plotting import figure
from bokeh.themes import DARK_MINIMAL, built_in_themes

from app.telemetry.balance import _balance_data
from app.telemetry.balance_metrics import _detailed_travel_stats
from app.telemetry.spectral import find_dominant_peak, welch_spectrum
from app.telemetry.travel import _travel_histogram_data
from app.telemetry.velocity import _normal_distribution_data, _velocity_histogram_data

# Distinct per-session colours (Bokeh Category10).
COMPARE_PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
]
LOWSPEED_THRESHOLD = 200.0
TRAVEL_REFERENCE_MM = 0.01
FLOOR_DB = -40.0
HIST_RANGE_MULT = 1.3
GROUND = '#dddddd'


@dataclass
class CompareSession:
    telemetry: object
    color: str
    name: str


def _suspension(telemetry, suspension_type):
    return telemetry.Front if suspension_type == 'front' else telemetry.Rear


def _legend(p, sessions, x, y_top, y_step, offset_idx=0):
    for i, s in enumerate(sessions):
        p.add_layout(Label(x=x, y=y_top - (i + offset_idx) * y_step, text=s.name,
                           text_color=s.color, text_font_size='12px',
                           text_align='right', x_offset=-6))


def _base(title, x_label, y_label):
    return figure(
        title=title, min_height=300, min_border_left=60,
        sizing_mode='stretch_both', toolbar_location='above',
        tools='pan,box_zoom,wheel_zoom,reset', active_drag='pan',
        x_axis_label=x_label, y_axis_label=y_label, output_backend='webgl')


# ---------------------------------------------------------------------------
# Travel histogram
# ---------------------------------------------------------------------------

def compare_travel_histogram_figure(sessions, suspension_type):
    title = f"{'Front' if suspension_type == 'front' else 'Rear'} travel histogram"
    p = _base(title, "Travel (mm)", "Time (%)")
    global_max_time = 0.0
    global_max_travel = 0.0

    for s in sessions:
        sus = _suspension(s.telemetry, suspension_type)
        if not sus.Present:
            continue
        max_travel = (s.telemetry.Linkage.MaxFrontTravel if suspension_type == 'front'
                      else s.telemetry.Linkage.MaxRearTravel)
        bins = sus.TravelBins
        hist = _travel_histogram_data(sus.Strokes, bins, max_travel)
        time = hist['time_perc']
        if not time or not bins:
            continue
        global_max_time = max(global_max_time, max(time))
        global_max_travel = max(global_max_travel, bins[-1])
        # Filled step polygon under the histogram.
        xs = [bins[0]]
        ys = [0.0]
        for i in range(len(time)):
            xs += [bins[i], bins[i + 1]]
            ys += [time[i], time[i]]
        xs.append(bins[-1])
        ys.append(0.0)
        p.patch(xs, ys, fill_color=s.color, fill_alpha=0.15,
                line_color=s.color, line_width=2)

    y_top = max(1.0, global_max_time) * HIST_RANGE_MULT
    p.x_range = Range1d(0, global_max_travel if global_max_travel > 0 else 1.0)
    p.y_range = Range1d(0, y_top)

    # Per-session avg / 95th / max guide lines + rotated labels.
    label_y = y_top * 0.92
    for s in sessions:
        sus = _suspension(s.telemetry, suspension_type)
        if not sus.Present:
            continue
        mx, avg, p95, _ = _detailed_travel_stats(sus)
        for loc, txt in ((avg, 'avg'), (p95, '95th'), (mx, 'max')):
            p.add_layout(Span(location=loc, dimension='height',
                              line_color=s.color, line_dash='dashed', line_width=2))
            p.add_layout(Label(x=loc, y=label_y, text=txt, text_color=s.color,
                               text_font_size='10px', text_align='center',
                               angle=math.pi / 2.0))
        label_y -= y_top * 0.08
    _legend(p, sessions, global_max_travel if global_max_travel > 0 else 1.0,
            y_top * 0.5 + (len(sessions) - 1) / 2.0 * y_top * 0.08, y_top * 0.08)
    return p


# ---------------------------------------------------------------------------
# Velocity histograms (full + low-speed)
# ---------------------------------------------------------------------------

def _velocity_totals(sus, hst, lowspeed):
    """Return (velocity-bin-centers, total-time%-per-bin) summed over travel bins."""
    sd, sd_low, _, _ = _velocity_histogram_data(
        sus.Strokes, hst, sus.TravelBins, sus.VelocityBins, sus.FineVelocityBins)
    src = sd_low if lowspeed else sd
    y = src.get('y') or []
    keys = [k for k in src.keys() if k != 'y']
    if not y or not keys:
        return np.array([]), np.array([])
    totals = np.sum([np.asarray(src[k], dtype=np.float64) for k in keys], axis=0)
    return np.asarray(y, dtype=np.float64), totals


def _velocity_histogram_common(sessions, suspension_type, title, x_label,
                               x_limit, lowspeed, x_scale):
    p = _base(title, x_label, "Time (%)")
    global_max_time = 0.0
    for s in sessions:
        sus = _suspension(s.telemetry, suspension_type)
        if not sus.Present:
            continue
        y, totals = _velocity_totals(sus, LOWSPEED_THRESHOLD, lowspeed)
        if y.size < 2:
            continue
        step = y[1] - y[0]
        xs, ys = [], []
        first = False
        for i in range(y.size):
            mid = y[i]
            if lowspeed and (mid <= -x_limit or mid >= x_limit):
                continue
            left = (mid - step / 2.0) * x_scale
            right = (mid + step / 2.0) * x_scale
            if not first:
                xs.append(left)
                ys.append(0.0)
                first = True
            xs += [left, right]
            ys += [totals[i], totals[i]]
            global_max_time = max(global_max_time, totals[i])
        if xs:
            xs.append(xs[-1])
            ys.append(0.0)
            p.patch(xs, ys, fill_color=s.color, fill_alpha=0.15,
                    line_color=s.color, line_width=2)
        # Normal-distribution overlay (dotted).
        step_unit = step  # mm/s
        vel_data = sus.Velocity
        nd = _normal_distribution_data(sus.Strokes, vel_data, step_unit)
        if nd['ny']:
            nx = np.asarray(nd['ny']) * x_scale
            p.line(nx.tolist(), nd['pdf'], line_color=s.color,
                   line_width=2, line_dash='dotted')

    y_top = max(1.0, global_max_time) * HIST_RANGE_MULT
    p.add_layout(Span(location=0, dimension='height',
                      line_color=GROUND, line_dash='dotted', line_width=1))
    p.x_range = Range1d(-x_limit * x_scale, x_limit * x_scale)
    p.y_range = Range1d(0, y_top)
    _legend(p, sessions, x_limit * x_scale, y_top * 0.95, y_top * 0.08)
    return p


def compare_velocity_histogram_figure(sessions, suspension_type):
    title = f"{'Front' if suspension_type == 'front' else 'Rear'} velocity histogram"
    # Full velocity range in m/s (x in m/s, +-2 m/s window).
    return _velocity_histogram_common(
        sessions, suspension_type, title, "Velocity (m/s)",
        x_limit=2000.0, lowspeed=False, x_scale=1 / 1000.0)


def compare_lowspeed_velocity_figure(sessions, suspension_type):
    title = f"{'Front' if suspension_type == 'front' else 'Rear'} low-speed velocity"
    # Low-speed window in mm/s (+-(threshold+50)).
    return _velocity_histogram_common(
        sessions, suspension_type, title, "Velocity (mm/s)",
        x_limit=LOWSPEED_THRESHOLD + 50.0, lowspeed=True, x_scale=1.0)


# ---------------------------------------------------------------------------
# Spectrum overlay
# ---------------------------------------------------------------------------

def compare_spectrum_figure(sessions, suspension_type):
    title = f"{'Front' if suspension_type == 'front' else 'Rear'} travel spectrum"
    p = figure(
        title=title, min_height=300, min_border_left=60,
        sizing_mode='stretch_both', toolbar_location='above',
        tools='pan,box_zoom,wheel_zoom,reset', active_drag='pan',
        x_axis_type='log', x_axis_label="Frequency (Hz)",
        y_axis_label="Amplitude (dB re 0.01 mm)",
        x_range=Range1d(0.3, 100.0), output_backend='webgl')
    y_min, y_max = math.inf, FLOOR_DB
    drew = False
    for s in sessions:
        sus = _suspension(s.telemetry, suspension_type)
        if not sus.Present or not sus.Travel or len(sus.Travel) < 64:
            continue
        freqs, amps = welch_spectrum(sus.Travel, s.telemetry.SampleRate)
        if freqs.size == 0:
            continue
        xs, ys = [], []
        for i in range(1, freqs.size):
            f = float(freqs[i])
            if f < 0.3:
                continue
            if f > 100.0:
                break
            amp = float(amps[i])
            db = max(20.0 * math.log10(amp / TRAVEL_REFERENCE_MM), FLOOR_DB) if amp > 0 else FLOOR_DB
            xs.append(f)
            ys.append(db)
            y_min = min(y_min, db)
            y_max = max(y_max, db)
        if xs:
            p.line(xs, ys, line_color=s.color, line_width=2)
            drew = True
            peak_f, peak_a = find_dominant_peak(freqs, amps, 1.3, 4.5)
            if np.isfinite(peak_f) and peak_a > 0:
                peak_db = max(20.0 * math.log10(peak_a / TRAVEL_REFERENCE_MM), FLOOR_DB)
                p.scatter([peak_f], [peak_db], marker='circle', size=10,
                          line_color=s.color, line_width=2, fill_color=None)
                p.add_layout(Span(location=peak_f, dimension='height',
                                  line_color=s.color, line_dash='dashed', line_width=1))
    if not drew:
        p.y_range = Range1d(FLOOR_DB, 0)
        return p
    y_bottom = math.floor(y_min / 10.0) * 10.0
    y_top = y_max + 6.0
    if y_top - y_bottom < 20.0:
        y_top = y_bottom + 20.0
    p.y_range = Range1d(y_bottom, y_top)
    _legend(p, sessions, 100.0, y_top, (y_top - y_bottom) * 0.07)
    return p


# ---------------------------------------------------------------------------
# Balance overlay (front solid / rear dashed per session)
# ---------------------------------------------------------------------------

def compare_balance_figure(sessions):
    p = _base("Balance", "Suspension travel (%)", "Velocity (mm/s)")
    p.xaxis.ticker = FixedTicker(ticks=list(range(0, 101, 10)))
    max_comp = max_reb = 0.0
    trends = []
    for s in sessions:
        t = s.telemetry
        if not (t.Front.Present and t.Rear.Present):
            continue
        cf, cr = _balance_data(t.Front.Strokes.Compressions, t.Rear.Strokes.Compressions,
                               t.Linkage.MaxFrontTravel, t.Linkage.MaxRearTravel)
        rf, rr = _balance_data(t.Front.Strokes.Rebounds, t.Rear.Strokes.Rebounds,
                               t.Linkage.MaxFrontTravel, t.Linkage.MaxRearTravel)
        trends.append((s, cf, cr, rf, rr))
        for d in (cf, cr, rf, rr):
            vals = [abs(v) for v in d.get('trend', []) if np.isfinite(v)]
            if vals:
                m = max(vals)
                if d in (cf, cr):
                    max_comp = max(max_comp, m)
                else:
                    max_reb = max(max_reb, m)

    rounded_comp = max(100, math.ceil(max_comp / 100.0) * 100)
    rounded_reb = max(100, math.ceil(max_reb / 100.0) * 100)
    p.add_layout(Span(location=0, dimension='width',
                      line_color=GROUND, line_dash='dotted', line_width=1))
    for s, cf, cr, rf, rr in trends:
        # Front solid, rear dashed; compression above 0, rebound below.
        p.line(cf.get('travel', []), cf.get('trend', []), line_color=s.color, line_width=2)
        p.line(rf.get('travel', []), rf.get('trend', []), line_color=s.color, line_width=2)
        p.line(cr.get('travel', []), cr.get('trend', []), line_color=s.color,
               line_width=2, line_dash='dashed')
        p.line(rr.get('travel', []), rr.get('trend', []), line_color=s.color,
               line_width=2, line_dash='dashed')
    p.x_range = Range1d(0, 100)
    p.y_range = Range1d(-rounded_reb, rounded_comp)
    step = max(rounded_comp, rounded_reb) * 0.08
    mid = (rounded_comp - rounded_reb) / 2.0
    top = mid + (len(trends) / 2.0) * step + step
    p.add_layout(Label(x=100, y=top, text="— Front   - - Rear",
                       text_color='#808080', text_font_size='10px',
                       text_align='right', x_offset=-6))
    for i, (s, *_rest) in enumerate(trends):
        p.add_layout(Label(x=100, y=top - (i + 1) * step, text=s.name,
                           text_color=s.color, text_font_size='12px',
                           text_align='right', x_offset=-6))
    return p


# ---------------------------------------------------------------------------
# Front/rear travel slope overlay
# ---------------------------------------------------------------------------

def compare_front_rear_scatter_figure(sessions):
    p = _base("Front vs rear travel", "Rear suspension travel (%)",
              "Front suspension travel (%)")
    p.xaxis.ticker = FixedTicker(ticks=list(range(0, 101, 10)))
    p.yaxis.ticker = FixedTicker(ticks=list(range(0, 101, 10)))
    p.line([0, 100], [0, 100], line_color=GROUND, line_width=1, line_dash='dashed')
    slopes = []
    for s in sessions:
        t = s.telemetry
        if not (t.Front.Present and t.Rear.Present):
            continue
        count = min(len(t.Front.Travel or []), len(t.Rear.Travel or []))
        if count == 0 or (t.Linkage.MaxRearTravel or 0) == 0 or (t.Linkage.MaxFrontTravel or 0) == 0:
            continue
        rear = np.asarray(t.Rear.Travel[:count]) / t.Linkage.MaxRearTravel * 100.0
        front = np.asarray(t.Front.Travel[:count]) / t.Linkage.MaxFrontTravel * 100.0
        denom = float(np.sum(rear * rear))
        if denom <= 0:
            continue
        slope = float(np.sum(rear * front) / denom)
        p.line([0, 100], [0, 100 * slope], line_color=s.color, line_width=2)
        slopes.append((s, slope))
    p.x_range = Range1d(0, 100)
    p.y_range = Range1d(0, 100)
    for i, (s, slope) in enumerate(slopes):
        p.add_layout(Label(x=100, y=2 + (len(slopes) - 1 - i) * 6,
                           text=f"{s.name}, a={slope:.2f}", text_color=s.color,
                           text_font_size='11px', text_align='right',
                           text_baseline='bottom', x_offset=-10))
    return p


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_comparison(sessions):
    """Build all comparison figures into one document.

    Returns ``(script, figures)`` where figures is a list of
    ``{'title': str, 'div': str}`` in render order.
    """
    any_front = any(_suspension(s.telemetry, 'front').Present for s in sessions)
    any_rear = any(_suspension(s.telemetry, 'rear').Present for s in sessions)
    any_dual = any(s.telemetry.Front.Present and s.telemetry.Rear.Present
                   for s in sessions)

    specs = []  # (title, figure)
    if any_front:
        specs.append(("Front travel histogram",
                      compare_travel_histogram_figure(sessions, 'front')))
        specs.append(("Front velocity histogram",
                      compare_velocity_histogram_figure(sessions, 'front')))
        specs.append(("Front low-speed velocity",
                      compare_lowspeed_velocity_figure(sessions, 'front')))
        specs.append(("Front travel spectrum",
                      compare_spectrum_figure(sessions, 'front')))
    if any_rear:
        specs.append(("Rear travel histogram",
                      compare_travel_histogram_figure(sessions, 'rear')))
        specs.append(("Rear velocity histogram",
                      compare_velocity_histogram_figure(sessions, 'rear')))
        specs.append(("Rear low-speed velocity",
                      compare_lowspeed_velocity_figure(sessions, 'rear')))
        specs.append(("Rear travel spectrum",
                      compare_spectrum_figure(sessions, 'rear')))
    if any_dual:
        specs.append(("Balance", compare_balance_figure(sessions)))
        specs.append(("Front vs rear travel",
                      compare_front_rear_scatter_figure(sessions)))

    document = Document()
    for _title, fig in specs:
        document.add_root(fig)

    theme = built_in_themes[DARK_MINIMAL]
    script, divs = components([fig for _t, fig in specs], theme=theme)
    figures = [{'title': t, 'div': d} for (t, _f), d in zip(specs, divs)]
    return script, figures
