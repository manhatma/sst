import numpy as np
from typing import Any, List
from flask import current_app

from bokeh.models import ColumnDataSource, FixedTicker, Label, Span
from bokeh.plotting import figure

from app.telemetry.psst import Stroke, Strokes


def _travel_velocity(strokes: List[Stroke], travel_max: float) -> (np.array, np.array):
    if not strokes:
        return np.array([]), np.array([])

    if travel_max == 0:
        current_app.logger.warning("_travel_velocity: travel_max is 0. Travel percentages will be 0.")
        t_values = [0.0 for _ in strokes]
    else:
        t_values = [s.Stat.MaxTravel / travel_max * 100 for s in strokes]
    
    v_values = [s.Stat.MaxVelocity for s in strokes]

    t_np = np.array(t_values)
    v_np = np.array(v_values)

    if t_np.size == 0:
         return np.array([]), np.array([])
         
    p = t_np.argsort()
    return t_np[p], v_np[p]


def _balance_data(front_strokes: List[Stroke], rear_strokes: List[Stroke],
                  front_max: float, rear_max: float) -> (
                  dict[str, Any], dict[str, Any]):
    ft, fv = _travel_velocity(front_strokes, front_max)
    rt, rv = _travel_velocity(rear_strokes, rear_max)

    f_trend_values = []
    f_slope = None
    if ft.size >= 2:
        try:
            fp = np.poly1d(np.polyfit(ft, fv, 1))
            f_trend_values = [fp(t_val) for t_val in ft]
            f_slope = fp.coefficients[0]
        except (np.RankWarning, TypeError, ValueError) as e:
            current_app.logger.warning(f"_balance_data: Could not compute front trend: {e}. Data points: {ft.size}")
            f_trend_values = [np.nan] * ft.size
    elif ft.size > 0:
        f_trend_values = [np.nan] * ft.size
    
    r_trend_values = []
    r_slope = None
    if rt.size >= 2:
        try:
            rp = np.poly1d(np.polyfit(rt, rv, 1))
            r_trend_values = [rp(t_val) for t_val in rt]
            r_slope = rp.coefficients[0]
        except (np.RankWarning, TypeError, ValueError) as e:
            current_app.logger.warning(f"_balance_data: Could not compute rear trend: {e}. Data points: {rt.size}")
            r_trend_values = [np.nan] * rt.size
    elif rt.size > 0:
        r_trend_values = [np.nan] * rt.size

    f = dict(travel=ft.tolist(), velocity=fv.tolist(), trend=f_trend_values, slope=f_slope)
    r = dict(travel=rt.tolist(), velocity=rv.tolist(), trend=r_trend_values, slope=r_slope)

    return f, r


def get_valid_color(color: Any) -> str:
    if isinstance(color, str):
        if color.startswith('#') and len(color) in (4, 7, 9):
            return color
        elif len(color) > 1:  # Assuming named colors have length >1
            return color
        else:
            return 'black'
    elif isinstance(color, tuple):
        if len(color) > 0:
            return get_valid_color(color[0])
        else:
            return 'black'
    else:
        return 'black'


def balance_figure(front_strokes: List[Stroke], rear_strokes: List[Stroke],
                   front_max: float, rear_max: float, flipped: bool,
                   front_color: tuple[str, ...], rear_color: tuple[str, ...],
                   name: str, title: str) -> figure:
    f, r = _balance_data(front_strokes, rear_strokes, front_max, rear_max)

    # Extract columnar data for sources, excluding scalar 'slope'
    front_data = {k: v for k, v in f.items() if k != 'slope'}
    rear_data = {k: v for k, v in r.items() if k != 'slope'}

    front_source = ColumnDataSource(name='ds_f', data=front_data)
    rear_source = ColumnDataSource(name='ds_r', data=rear_data)

    x_range_end = 100.0
    final_f_travel = f.get('travel', [])
    final_r_travel = r.get('travel', [])

    if final_f_travel and final_r_travel:
        x_range_end = np.fmax(final_f_travel[-1] if final_f_travel else 0, final_r_travel[-1] if final_r_travel else 0)
    elif final_f_travel:
        x_range_end = final_f_travel[-1] if final_f_travel else 0
    elif final_r_travel:
        x_range_end = final_r_travel[-1] if final_r_travel else 0

    if not np.isfinite(x_range_end) or x_range_end <= 0:
        x_range_end = 100.0

    # Add padding to x_range_end to prevent label clipping
    x_range_end = max(x_range_end + 5, 105.0)

    p = figure(
        name=name,
        title=title,
        height=600,
        x_range=(0, x_range_end),
        sizing_mode="stretch_width",
        toolbar_location=None,
        tools='',
        x_axis_label="Travel (%)",
        y_axis_label="Velocity (mm/s)",
        output_backend='webgl')

    p.xaxis.ticker = FixedTicker(ticks=list(range(0, 110, 10)))
    p.y_range.flipped = flipped

    p.scatter(
        'travel', 'velocity',
        legend_label="Front",
        size=4,
        color=front_color,
        alpha=0.3,
        source=front_source)
    p.line(
        'travel', 'trend',
        line_width=2,
        color=front_color,
        source=front_source)

    p.scatter(
        'travel', 'velocity',
        legend_label="Rear",
        size=4,
        color=rear_color,
        alpha=0.6,
        source=rear_source)
    p.line(
        'travel', 'trend',
        line_width=2,
        color=rear_color,
        source=rear_source)

    p.legend.location = 'top_left'

    # Add slope labels
    front_label = None
    rear_label = None
    final_f_trend = f.get('trend', [])
    final_r_trend = r.get('trend', [])

    has_front = 'slope' in f and f['slope'] is not None and final_f_travel and final_f_trend and not np.isnan(final_f_trend[-1])
    has_rear = 'slope' in r and r['slope'] is not None and final_r_travel and final_r_trend and not np.isnan(final_r_trend[-1])

    last_y_f = final_f_trend[-1] if has_front else None
    last_y_r = final_r_trend[-1] if has_rear else None

    default_y_offset = 10  # Always positive to place above visually
    front_y_offset = default_y_offset
    rear_y_offset = default_y_offset

    if has_front and has_rear and abs(f['slope'] - r['slope']) < 5.0:
        is_front_higher_screen = (last_y_f > last_y_r) if not flipped else (last_y_f < last_y_r)
        if is_front_higher_screen:
            front_y_offset = 25
            rear_y_offset = 5
        else:
            front_y_offset = 5
            rear_y_offset = 25

    if has_front:
        last_x = final_f_travel[-1]
        last_y = last_y_f
        front_text_color = get_valid_color(front_color)
        front_label = Label(
            x=last_x,
            y=last_y,
            x_offset=10,
            y_offset=front_y_offset,
            text=f"{f['slope']:.1f}",
            text_font_size="11pt",
            text_color=front_text_color,
            text_baseline="middle",
            text_align="left",
            background_fill_color="#282828",
            background_fill_alpha=0.9,
            border_line_color=None,
            border_line_alpha=0.8,
            border_line_width=1,
        )
        p.add_layout(front_label)

    if has_rear:
        last_x = final_r_travel[-1]
        last_y = last_y_r
        rear_text_color = get_valid_color(rear_color)
        rear_label = Label(
            x=last_x,
            y=last_y,
            x_offset=10,
            y_offset=rear_y_offset,
            text=f"{r['slope']:.1f}",
            text_font_size="11pt",
            text_color=rear_text_color,
            text_baseline="middle",
            text_align="left",
            background_fill_color="#282828",
            background_fill_alpha=0.9,
            border_line_color=None,
            border_line_alpha=0.8,
            border_line_width=1,
        )
        p.add_layout(rear_label)

    return p


def update_balance(front_strokes: List[Stroke], rear_strokes: List[Stroke],
                   front_max: float, rear_max: float):
    f_data, r_data = _balance_data(
        front_strokes, rear_strokes, front_max, rear_max)

    range_end_val = 100.0
    final_f_travel_update = f_data.get('travel', [])
    final_r_travel_update = r_data.get('travel', [])

    if final_f_travel_update and final_r_travel_update:
        range_end_val = np.fmax(final_f_travel_update[-1] if final_f_travel_update else 0, final_r_travel_update[-1] if final_r_travel_update else 0)
    elif final_f_travel_update:
        range_end_val = final_f_travel_update[-1] if final_f_travel_update else 0
    elif final_r_travel_update:
        range_end_val = final_r_travel_update[-1] if final_r_travel_update else 0
        
    if not np.isfinite(range_end_val) or range_end_val <= 0:
        range_end_val = 100.0

    # Add padding to range_end_val consistent with balance_figure
    range_end_val = max(range_end_val + 5, 105.0)

    # To prevent validation errors in updates, exclude 'slope' from data dicts
    f_data_no_slope = {k: v for k, v in f_data.items() if k != 'slope'}
    r_data_no_slope = {k: v for k, v in r_data.items() if k != 'slope'}

    return dict(
        f_data=f_data_no_slope,
        r_data=r_data_no_slope,
        f_slope=f_data.get('slope'),
        r_slope=r_data.get('slope'),
        range_end=range_end_val
    )


def velocity_balance_comparison_figure(
    front_strokes: Strokes,
    rear_strokes: Strokes,
    front_max: float,
    rear_max: float,
    front_color,
    rear_color,
) -> figure:
    """Combined compression + rebound velocity trendlines in a single chart.

    Compression trendlines sit above the y=0 line (positive velocity),
    rebound trendlines sit below it (negated to negative velocity).
    Lines only, no scatter dots.
    """
    cf, cr = _balance_data(
        front_strokes.Compressions, rear_strokes.Compressions,
        front_max, rear_max)
    rf, rr = _balance_data(
        front_strokes.Rebounds, rear_strokes.Rebounds,
        front_max, rear_max)

    # x_range: max travel across all datasets + padding
    all_travel = (cf.get('travel', []) + cr.get('travel', []) +
                  rf.get('travel', []) + rr.get('travel', []))
    x_range_end = 105.0
    if all_travel:
        finite_travel = [v for v in all_travel if np.isfinite(v) and v > 0]
        if finite_travel:
            x_range_end = max(max(finite_travel) + 5, 105.0)

    # Symmetric y_range based on max absolute trendline value
    # Rebound MaxVelocity is already negative, so trendlines sit below y=0 naturally
    all_trends = (cf.get('trend', []) + cr.get('trend', []) +
                  rf.get('trend', []) + rr.get('trend', []))
    finite_trends = [v for v in all_trends if np.isfinite(v)]
    max_trend = max(abs(v) for v in finite_trends) if finite_trends else 500.0
    y_pad = max(max_trend * 1.3, 100.0)

    vc_f_source = ColumnDataSource(name='ds_vc_f', data={
        'travel': cf.get('travel', []),
        'trend': cf.get('trend', []),
    })
    vc_r_source = ColumnDataSource(name='ds_vc_r', data={
        'travel': cr.get('travel', []),
        'trend': cr.get('trend', []),
    })
    vr_f_source = ColumnDataSource(name='ds_vr_f', data={
        'travel': rf.get('travel', []),
        'trend': rf.get('trend', []),
    })
    vr_r_source = ColumnDataSource(name='ds_vr_r', data={
        'travel': rr.get('travel', []),
        'trend': rr.get('trend', []),
    })

    p = figure(
        name='velocity_balance_comp',
        title="Velocity balance comparison",
        min_height=420,
        x_range=(0, x_range_end),
        y_range=(-y_pad, y_pad),
        sizing_mode='stretch_both',
        toolbar_location=None,
        tools='',
        x_axis_label="Travel (%)",
        y_axis_label="Velocity (mm/s)",
        output_backend='webgl')

    p.xaxis.ticker = FixedTicker(ticks=list(range(0, 110, 10)))

    # Horizontal zero-line separating compression (above) from rebound (below)
    p.add_layout(Span(location=0, dimension='width',
                      line_color='#888888', line_dash='dashed', line_width=1))

    front_color_str = get_valid_color(front_color)
    rear_color_str = get_valid_color(rear_color)

    # Compression trendlines (positive side)
    p.line('travel', 'trend', line_width=2, color=front_color,
           legend_label="Front", source=vc_f_source)
    p.line('travel', 'trend', line_width=2, color=rear_color,
           legend_label="Rear", source=vc_r_source)
    # Rebound trendlines (negative side)
    p.line('travel', 'trend', line_width=2, color=front_color,
           legend_label="Front", source=vr_f_source)
    p.line('travel', 'trend', line_width=2, color=rear_color,
           legend_label="Rear", source=vr_r_source)

    p.legend.location = 'top_left'
    p.legend.click_policy = 'hide'

    def _slope_label(travel_list, trend_list, slope, color_str, y_offset):
        if not travel_list or not trend_list or slope is None:
            return
        last_t = travel_list[-1]
        last_v = trend_list[-1]
        if not np.isfinite(last_v) or not np.isfinite(last_t):
            return
        p.add_layout(Label(
            x=last_t, y=last_v,
            x_offset=10, y_offset=y_offset,
            text=f"{slope:.1f}",
            text_font_size="11pt",
            text_color=color_str,
            text_baseline="middle",
            text_align="left",
            background_fill_color="#282828",
            background_fill_alpha=0.9,
            border_line_color=None,
        ))

    _slope_label(cf.get('travel', []), cf.get('trend', []),
                 cf.get('slope'), front_color_str, 10)
    _slope_label(cr.get('travel', []), cr.get('trend', []),
                 cr.get('slope'), rear_color_str, -10)
    _slope_label(rf.get('travel', []), rf.get('trend', []),
                 rf.get('slope'), front_color_str, -10)
    _slope_label(rr.get('travel', []), rr.get('trend', []),
                 rr.get('slope'), rear_color_str, 10)

    return p
