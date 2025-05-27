import numpy as np
from typing import Any, List
from flask import current_app

from bokeh.models import ColumnDataSource
from bokeh.models.tickers import FixedTicker
from bokeh.plotting import figure

from app.telemetry.psst import Stroke


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
    if ft.size >= 2:
        try:
            fp = np.poly1d(np.polyfit(ft, fv, 1))
            f_trend_values = [fp(t_val) for t_val in ft]
        except (np.RankWarning, TypeError, ValueError) as e:
            current_app.logger.warning(f"_balance_data: Could not compute front trend: {e}. Data points: {ft.size}")
            f_trend_values = [np.nan] * ft.size
    elif ft.size > 0:
        f_trend_values = [np.nan] * ft.size
    
    r_trend_values = []
    if rt.size >= 2:
        try:
            rp = np.poly1d(np.polyfit(rt, rv, 1))
            r_trend_values = [rp(t_val) for t_val in rt]
        except (np.RankWarning, TypeError, ValueError) as e:
            current_app.logger.warning(f"_balance_data: Could not compute rear trend: {e}. Data points: {rt.size}")
            r_trend_values = [np.nan] * rt.size
    elif rt.size > 0:
        r_trend_values = [np.nan] * rt.size

    f = dict(travel=ft.tolist(), velocity=fv.tolist(), trend=f_trend_values)
    r = dict(travel=rt.tolist(), velocity=rv.tolist(), trend=r_trend_values)

    return f, r


def balance_figure(front_strokes: List[Stroke], rear_strokes: List[Stroke],
                   front_max: float, rear_max: float, flipped: bool,
                   front_color: tuple[str, ...], rear_color: tuple[str, ...],
                   name: str, title: str) -> figure:
    f, r = _balance_data(front_strokes, rear_strokes, front_max, rear_max)
    front_source = ColumnDataSource(name='ds_f', data=f)
    rear_source = ColumnDataSource(name='ds_r', data=r)

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

    return dict(
        f_data=f_data,
        r_data=r_data,
        range_end=range_end_val
    )