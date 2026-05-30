"""Discipline-aware balance metrics, ported from Sufni.Bridge.

``calculate_balance_metrics`` mirrors ``TelemetryData.CalculateBalanceMetrics``
(TelemetryData.cs:1720); the status/format helpers mirror
``BalanceMetricsViewModel`` (ViewModels/SessionPages/BalancePageViewModel.cs).
``balance_metrics_figure`` renders the ~26 metrics as a colour-coded HTML table
inside a Bokeh ``Div`` styled for the dashboard's DARK_MINIMAL theme.

The effective-head-angle metric needs ``Linkage.Wheelbase``, which the dashboard
linkage/.psst does not carry, so it is gated out (the row is omitted) — exactly
the behaviour the plan calls for.
"""

import math

import numpy as np
from bokeh.models import Div

from app.telemetry.spectral import (
    find_dominant_peak,
    frequency_split_for,
    integrate_band,
    mean_coherence,
    welch_cross_spectrum,
    welch_spectrum,
)

# Status colours (BalanceMetricRow.ValueBrush).
COLOR_GOOD = '#6CC44A'
COLOR_ACCEPTABLE = '#E0B83A'
COLOR_CRITICAL = '#E06A55'
COLOR_UNKNOWN = '#D0D0D0'

GOOD, ACCEPTABLE, CRITICAL, UNKNOWN = 'good', 'acceptable', 'critical', 'unknown'
_STATUS_COLOR = {
    GOOD: COLOR_GOOD,
    ACCEPTABLE: COLOR_ACCEPTABLE,
    CRITICAL: COLOR_CRITICAL,
    UNKNOWN: COLOR_UNKNOWN,
}

_MIN_SEGMENT = 8192


# ---------------------------------------------------------------------------
# Metric computation (mirrors CalculateBalanceMetrics)
# ---------------------------------------------------------------------------

def _detailed_travel_stats(suspension):
    """Mirror CalculateDetailedTravelStatistics: (max, avg, p95, bottomouts)."""
    travel = suspension.Travel or []
    n = len(travel)
    values = []
    bottomouts = 0
    strokes = (suspension.Strokes.Compressions or []) + (suspension.Strokes.Rebounds or [])
    for s in strokes:
        bottomouts += int(s.Stat.Bottomouts or 0)
        if s.End < s.Start or s.Start < 0 or s.End >= n:
            continue
        values.extend(travel[s.Start:s.End + 1])
    if not values:
        return 0.0, 0.0, 0.0, 0
    arr = np.asarray(values, dtype=np.float64)
    return float(arr.max()), float(arr.mean()), float(np.percentile(arr, 95)), bottomouts


def _velocity_stats(suspension):
    """Mirror CalculateVelocityStatistics: (avg_rebound, avg_compression)."""
    csum = ccount = 0.0
    for c in (suspension.Strokes.Compressions or []):
        csum += c.Stat.SumVelocity or 0.0
        ccount += c.Stat.Count or 0
    rsum = rcount = 0.0
    for r in (suspension.Strokes.Rebounds or []):
        rsum += r.Stat.SumVelocity or 0.0
        rcount += r.Stat.Count or 0
    avg_comp = csum / ccount if ccount > 0 else 0.0
    avg_reb = rsum / rcount if rcount > 0 else 0.0
    return avg_reb, avg_comp


def _travel_velocity(strokes, travel_max):
    """Sorted (travel%, max-velocity) arrays for the balance polynomial."""
    if not strokes or travel_max == 0:
        return np.array([]), np.array([])
    t = np.array([s.Stat.MaxTravel / travel_max * 100.0 for s in strokes])
    v = np.array([s.Stat.MaxVelocity for s in strokes])
    order = t.argsort()
    return t[order], v[order]


def _balance_msd(front, rear, front_max, rear_max, rebound):
    """Mirror CalculateBalance + the MSD normalisation in CalculateBalanceMetrics."""
    fs = front.Strokes.Rebounds if rebound else front.Strokes.Compressions
    rs = rear.Strokes.Rebounds if rebound else rear.Strokes.Compressions
    ft, fv = _travel_velocity(fs, front_max)
    rt, rv = _travel_velocity(rs, rear_max)
    if ft.size < 2 or rt.size < 2:
        return None
    try:
        fp = np.polyfit(ft, fv, 1)
        rp = np.polyfit(rt, rv, 1)
    except (TypeError, ValueError, np.linalg.LinAlgError):
        return None
    eval_pts = np.arange(100) + 0.5
    msd = float(np.mean(np.polyval(fp, eval_pts) - np.polyval(rp, eval_pts)))
    mv = max(np.abs(fv).max() if fv.size else 0.0,
             np.abs(rv).max() if rv.size else 0.0)
    if mv <= 1e-6:
        return None
    return msd / mv * 100.0


def _michelson(a, b):
    return (a - b) / (a + b)


def calculate_balance_metrics(telemetry, discipline=None) -> dict:
    """Return a dict mirroring the C# ``BalanceMetrics`` record fields."""
    front, rear = telemetry.Front, telemetry.Rear
    linkage = telemetry.Linkage
    fs = telemetry.SampleRate
    max_f = linkage.MaxFrontTravel or 0
    max_r = linkage.MaxRearTravel or 0
    f_split = frequency_split_for(discipline)

    m = {k: None for k in (
        'front_sag', 'rear_sag', 'sag_diff', 'front_p95', 'rear_p95', 'p95_diff',
        'front_bo', 'rear_bo', 'comp_ratio', 'reb_ratio', 'comp_msd', 'reb_msd',
        'front_peak', 'rear_peak', 'freq_diff', 'amp_ratio',
        'low_energy_db', 'mid_energy_db', 'wheel_energy_db', 'high_energy_db',
        'low_coh', 'mid_coh', 'wheel_coh', 'high_coh',
        'ha_static', 'ha_shift')}
    m['freq_split'] = f_split

    if front.Present:
        _mx, avg, p95, bo = _detailed_travel_stats(front)
        if max_f > 0:
            m['front_sag'] = avg / max_f * 100.0
            m['front_p95'] = p95 / max_f * 100.0
        m['front_bo'] = bo
    if rear.Present:
        _mx, avg, p95, bo = _detailed_travel_stats(rear)
        if max_r > 0:
            m['rear_sag'] = avg / max_r * 100.0
            m['rear_p95'] = p95 / max_r * 100.0
        m['rear_bo'] = bo
    if m['front_sag'] is not None and m['rear_sag'] is not None:
        m['sag_diff'] = abs(m['front_sag'] - m['rear_sag'])
    if m['front_p95'] is not None and m['rear_p95'] is not None:
        m['p95_diff'] = abs(m['front_p95'] - m['rear_p95'])

    # Effective head angle: needs Linkage.Wheelbase (not present on the
    # dashboard linkage) -> stays None, row omitted by the figure builder.
    wheelbase = getattr(linkage, 'Wheelbase', None)
    if (wheelbase and wheelbase > 0 and (linkage.MaxFrontStroke or 0) > 0
            and max_r > 0 and m['front_sag'] is not None and m['rear_sag'] is not None):
        ha_rad = linkage.HeadAngle * math.pi / 180.0
        sf = m['front_sag'] / 100.0 * linkage.MaxFrontStroke
        sr = m['rear_sag'] / 100.0 * max_r
        phi = math.atan2(sr - sf * math.sin(ha_rad), wheelbase)
        m['ha_static'] = linkage.HeadAngle
        m['ha_shift'] = -phi * 180.0 / math.pi

    if front.Present and rear.Present:
        f_reb, f_comp = _velocity_stats(front)
        r_reb, r_comp = _velocity_stats(rear)
        if f_comp + r_comp > 1e-6:
            m['comp_ratio'] = _michelson(f_comp, r_comp)
        fr, rr = abs(f_reb), abs(r_reb)
        if fr + rr > 1e-6:
            m['reb_ratio'] = _michelson(fr, rr)
        m['comp_msd'] = _balance_msd(front, rear, max_f, max_r, rebound=False)
        m['reb_msd'] = _balance_msd(front, rear, max_f, max_r, rebound=True)

    f_amp = r_amp = None
    if front.Present and front.Travel and len(front.Travel) >= _MIN_SEGMENT:
        freqs, amps = welch_spectrum(front.Travel, fs)
        if amps.size:
            f, a = find_dominant_peak(freqs, amps, 1.3, 4.5)
            if not math.isnan(f):
                m['front_peak'], f_amp = f, a
    if rear.Present and rear.Travel and len(rear.Travel) >= _MIN_SEGMENT:
        freqs, amps = welch_spectrum(rear.Travel, fs)
        if amps.size:
            f, a = find_dominant_peak(freqs, amps, 1.3, 4.5)
            if not math.isnan(f):
                m['rear_peak'], r_amp = f, a
    if m['front_peak'] is not None and m['rear_peak'] is not None:
        m['freq_diff'] = abs(m['front_peak'] - m['rear_peak'])
    if f_amp is not None and r_amp is not None and f_amp + r_amp > 1e-9:
        m['amp_ratio'] = _michelson(f_amp, r_amp)

    if (front.Present and rear.Present and front.Travel and rear.Travel
            and len(front.Travel) >= _MIN_SEGMENT and len(rear.Travel) >= _MIN_SEGMENT
            and len(front.Travel) == len(rear.Travel)):
        cf, pxx, pyy, pxy = welch_cross_spectrum(front.Travel, rear.Travel, fs)
        if cf.size:
            def ratio_db(lo, hi):
                ef = integrate_band(cf, pxx, lo, hi)
                er = integrate_band(cf, pyy, lo, hi)
                if ef <= 0 or er <= 0:
                    return None
                return 10.0 * math.log10(ef / er)
            m['low_energy_db'] = ratio_db(1.0, f_split)
            m['mid_energy_db'] = ratio_db(f_split, 10.0)
            m['wheel_energy_db'] = ratio_db(10.0, 25.0)
            m['high_energy_db'] = ratio_db(25.0, 50.0)
            m['low_coh'] = mean_coherence(cf, pxx, pyy, pxy, 1.0, f_split)
            m['mid_coh'] = mean_coherence(cf, pxx, pyy, pxy, f_split, 10.0)
            m['wheel_coh'] = mean_coherence(cf, pxx, pyy, pxy, 10.0, 25.0)
            m['high_coh'] = mean_coherence(cf, pxx, pyy, pxy, 25.0, 50.0)

    return m


# ---------------------------------------------------------------------------
# Status + formatting (mirror BalanceMetricsViewModel.Set*)
# ---------------------------------------------------------------------------

def _signed(v, dec):
    if v > 0:
        return f"+{v:.{dec}f}"
    if v < 0:
        return f"{v:.{dec}f}"
    return f"{0.0:.{dec}f}"


def _row(label, value, target, status):
    return dict(label=label, value=value, target=target, status=status)


def _na(label, target):
    return _row(label, "—", target, UNKNOWN)


def _sag_band(label, value, target, good_lo, good_hi):
    if value is None:
        return _na(label, target)
    status = (GOOD if good_lo <= value <= good_hi
              else ACCEPTABLE if good_lo - 2 <= value <= good_hi + 2
              else CRITICAL)
    return _row(label, f"{value:.1f} %", target, status)


def _threshold(label, value, target, fmt, good_cutoff, acc_cutoff, lower_is_better):
    if value is None:
        return _na(label, target)
    if lower_is_better:
        status = (GOOD if value <= good_cutoff
                  else ACCEPTABLE if value <= acc_cutoff else CRITICAL)
    else:
        status = (GOOD if value > good_cutoff
                  else ACCEPTABLE if value > acc_cutoff else CRITICAL)
    return _row(label, fmt.format(value), target, status)


def _count(label, value, target):
    if value is None:
        return _na(label, target)
    status = GOOD if value == 0 else ACCEPTABLE if value <= 5 else CRITICAL
    return _row(label, f"{value} times", target, status)


def _signed_band(label, value, target, good_lo, good_hi, acc_lo, acc_hi):
    if value is None:
        return _na(label, target)
    status = (GOOD if good_lo <= value <= good_hi
              else ACCEPTABLE if acc_lo <= value <= acc_hi else CRITICAL)
    return _row(label, _signed(value, 2), target, status)


def _msd(label, value, target):
    if value is None:
        return _na(label, target)
    a = abs(value)
    status = GOOD if a <= 5 else ACCEPTABLE if a <= 15 else CRITICAL
    return _row(label, f"{_signed(value, 2)} %", target, status)


def _msd_rebound(label, value, target):
    if value is None:
        return _na(label, target)
    status = (GOOD if -10 <= value <= 0
              else CRITICAL if abs(value) >= 15 else ACCEPTABLE)
    return _row(label, f"{_signed(value, 2)} %", target, status)


def _freq_band(label, value, target, good_lo, good_hi):
    if value is None:
        return _na(label, target)
    status = (GOOD if good_lo <= value <= good_hi
              else ACCEPTABLE if good_lo - 0.5 <= value <= good_hi + 0.5
              else CRITICAL)
    return _row(label, f"{value:.2f} Hz", target, status)


def _freq_diff(label, value, target):
    if value is None:
        return _na(label, target)
    status = GOOD if value <= 0.4 else ACCEPTABLE if value <= 0.7 else CRITICAL
    return _row(label, f"{value:.2f} Hz", target, status)


def _energy_db(label, value, target):
    if value is None:
        return _na(label, target)
    a = abs(value)
    status = GOOD if a <= 2.0 else ACCEPTABLE if a <= 4.0 else CRITICAL
    return _row(label, f"{_signed(value, 1)} dB", target, status)


def _coherence(label, value, target, higher_is_better, good_cutoff=None):
    if value is None:
        return _na(label, target)
    buffer, epsilon = 0.2, 5e-3
    if higher_is_better:
        cutoff = good_cutoff if good_cutoff is not None else 0.7
        status = (GOOD if value >= cutoff - epsilon
                  else ACCEPTABLE if value >= cutoff - buffer - epsilon else CRITICAL)
    else:
        cutoff = good_cutoff if good_cutoff is not None else 0.4
        status = (GOOD if value <= cutoff + epsilon
                  else ACCEPTABLE if value <= cutoff + buffer + epsilon else CRITICAL)
    return _row(label, f"{value:.2f}", target, status)


def _freq_bands(discipline):
    key = (discipline or 'enduro')
    if isinstance(key, str):
        key = key.strip().lower()
    if key in ('xc', 0):
        return 3.0, 3.9, 3.0, 3.6
    if key in ('downhill', 2):
        return 1.7, 2.5, 1.7, 2.3
    return 2.1, 3.2, 2.1, 2.9  # Enduro / default


def build_rows(m: dict, discipline=None) -> list[dict]:
    """Build the labelled, colour-coded metric rows (mirrors Apply)."""
    f_split = m.get('freq_split') or 2.0
    fs = f"{f_split:.1f}"
    front_lo, front_hi, rear_lo, rear_hi = _freq_bands(discipline)
    rows = [
        _sag_band("Front SAG (dyn.)", m['front_sag'], "23–28 %", 23, 28),
        _sag_band("Rear SAG (dyn.)", m['rear_sag'], "28–33 %", 28, 33),
        _threshold("Sag-Diff |F−R|", m['sag_diff'], "≤ 5 pp", "{:.1f} pp", 5.0, 8.0, True),
        _threshold("Front 95th", m['front_p95'], "> 55 %", "{:.1f} %", 55.0, 50.0, False),
        _threshold("Rear 95th", m['rear_p95'], "> 55 %", "{:.1f} %", 55.0, 50.0, False),
        _threshold("95th-Diff |F−R|", m['p95_diff'], "≤ 5 pp", "{:.1f} pp", 5.0, 10.0, True),
        _count("Front Bottom-out", m['front_bo'], "≈ 0"),
        _count("Rear Bottom-out", m['rear_bo'], "≈ 0"),
        _signed_band("Comp Vel F/R", m['comp_ratio'], "−0.08 … +0.07",
                     -0.0811, 0.0698, -0.1111, 0.0909),
        _signed_band("Reb Vel F/R", m['reb_ratio'], "0.00 … +0.07",
                     0.0, 0.0698, 0.0, 0.0909),
        _msd("MSD Compression", m['comp_msd'], "≈ 0"),
        _msd_rebound("MSD Rebound", m['reb_msd'], "−10 to 0 %"),
        _freq_band("Front Eigenfreq.", m['front_peak'],
                   f"{front_lo:.1f}–{front_hi:.1f} Hz", front_lo, front_hi),
        _freq_band("Rear Eigenfreq.", m['rear_peak'],
                   f"{rear_lo:.1f}–{rear_hi:.1f} Hz", rear_lo, rear_hi),
        _freq_diff("Frequency-Diff |F−R|", m['freq_diff'], "≤ 0.4 Hz"),
        _signed_band("Peak Amp F/R", m['amp_ratio'], "−0.05 … +0.05",
                     -0.0526, 0.0476, -0.1111, 0.0909),
        _energy_db(f"Energy F/R (1.0–{fs} Hz)", m['low_energy_db'], "0 dB ±2"),
        _energy_db(f"Energy F/R ({fs}–10.0 Hz)", m['mid_energy_db'], "0 dB ±2"),
        _energy_db("Energy F/R (10.0–25.0 Hz)", m['wheel_energy_db'], "0 dB ±2"),
        _energy_db("Energy F/R (25.0–50.0 Hz)", m['high_energy_db'], "0 dB ±2"),
        _coherence(f"Coherence (1.0–{fs} Hz)", m['low_coh'], "≥ 0.7", True),
        _coherence(f"Coherence ({fs}–10.0 Hz)", m['mid_coh'], "≤ 0.4", False),
        _coherence("Coherence (10.0–25.0 Hz)", m['wheel_coh'], "≤ 0.4", False),
        _coherence("Coherence (25.0–50.0 Hz)", m['high_coh'], "≤ 0.1", False, good_cutoff=0.1),
    ]
    # Effective head angle only when wheelbase was available.
    if m.get('ha_static') is not None and m.get('ha_shift') is not None:
        eff = m['ha_static'] + m['ha_shift']
        rows.insert(6, _row("Eff. Head Angle", f"{eff:.1f}°",
                            f"{m['ha_static']:.1f}°", UNKNOWN))
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _table_html(rows, discipline) -> str:
    disc = (discipline or 'enduro')
    disc_label = {'xc': 'Cross-country', 'enduro': 'Enduro',
                  'downhill': 'Downhill'}.get(str(disc).lower(), str(disc).title())
    body = []
    for r in rows:
        color = _STATUS_COLOR[r['status']]
        body.append(
            '<tr>'
            f'<td class="bm-label">{r["label"]}</td>'
            f'<td class="bm-value" style="color:{color}">{r["value"]}</td>'
            f'<td class="bm-target">{r["target"]}</td>'
            '</tr>')
    return (
        '<div class="balance-metrics">'
        f'<div class="bm-header">Balance metrics '
        f'<span class="bm-discipline">({disc_label})</span></div>'
        '<table class="bm-table">'
        '<thead><tr><th>Metric</th><th>Value</th><th>Target</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody>'
        '</table></div>')


def balance_metrics_figure(telemetry, discipline=None) -> Div:
    """Bokeh ``Div`` with the colour-coded balance-metrics table (dual only)."""
    m = calculate_balance_metrics(telemetry, discipline)
    rows = build_rows(m, discipline)
    return Div(name='balance_metrics', sizing_mode='stretch_both',
              stylesheets=[_TABLE_CSS], text=_table_html(rows, discipline))


# Scoped stylesheet shipped with the Div so the table renders without relying on
# a frontend rebuild; the frontend CSS may override/extend it for layout.
_TABLE_CSS = """
.balance-metrics { color: #d0d0d0; font-family: var(--bokeh-font, sans-serif);
  width: 100%; box-sizing: border-box; padding: 6px 10px; }
.bm-header { font-size: 15px; font-weight: 600; margin-bottom: 8px; color: #e8e8e8; }
.bm-discipline { font-weight: 400; color: #9aa0a6; font-size: 13px; }
.bm-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.bm-table th { text-align: left; color: #9aa0a6; font-weight: 500;
  border-bottom: 1px solid #3a3f44; padding: 4px 8px; }
.bm-table td { padding: 3px 8px; border-bottom: 1px solid #2a2e32; }
.bm-table tr:hover td { background: #23272b; }
.bm-label { color: #c8ccd0; }
.bm-value { font-variant-numeric: tabular-nums; font-weight: 600; text-align: right;
  font-family: Menlo, monospace; white-space: nowrap; }
.bm-target { color: #80868b; text-align: right; white-space: nowrap; }
"""
