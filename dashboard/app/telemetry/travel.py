import numpy as np
from flask import current_app # type: ignore
from typing import Tuple, List

from bokeh.events import DoubleTap, SelectionGeometry # type: ignore
from bokeh.models import ColumnDataSource # type: ignore
from bokeh.models.annotations import BoxAnnotation, Label, Span # type: ignore
from bokeh.models.axes import LinearAxis # type: ignore
from bokeh.models.callbacks import CustomJS # type: ignore
from bokeh.models.ranges import Range1d # type: ignore
from bokeh.models.tools import BoxSelectTool, CrosshairTool, WheelZoomTool # type: ignore
from bokeh.palettes import Spectral11 # type: ignore
from bokeh.plotting import figure # type: ignore
from bokeh.models.tickers import SingleIntervalTicker # type: ignore

from app.telemetry.psst import Airtime, Strokes, Telemetry, Suspension

HISTOGRAM_RANGE_MULTIPLIER = 1.3

def to_percentage(value: float, max_value: float) -> float:
    if max_value is None or max_value == 0:
        return 0.0
    return (value / max_value) * 100.0

def _travel_histogram_data(
    strokes: Strokes,
    bins_mm: list[float],
    theoretical_max_travel_mm: float
) -> dict[str, list[float]]:
    hist_len = len(bins_mm) - 1 if bins_mm and len(bins_mm) > 1 else 0
    hist = np.zeros(hist_len)
    total_count = 0

    if hist_len > 0 and strokes:
        for s in (strokes.Compressions or []) + (strokes.Rebounds or []):
            if hasattr(s, 'Stat') and s.Stat is not None and hasattr(s, 'DigitizedTravel') and s.DigitizedTravel is not None:
                total_count += s.Stat.Count
                for d_idx in s.DigitizedTravel:
                    if 0 <= d_idx < hist_len:
                        hist[d_idx] += 1
        if total_count > 0:
            hist = hist / total_count * 100.0

    bin_mids_mm = []
    bin_mids_perc = []
    bin_widths_perc = []

    if hist_len > 0 and theoretical_max_travel_mm > 0:
        bin_mids_mm_np = (np.array(bins_mm[:-1]) + np.array(bins_mm[1:])) / 2.0
        bin_mids_mm = bin_mids_mm_np.tolist()
        bin_mids_perc = (bin_mids_mm_np / theoretical_max_travel_mm * 100.0).tolist()
        bin_edges_perc_np = np.array(bins_mm) / theoretical_max_travel_mm * 100.0
        full_bin_widths_perc_np = np.diff(bin_edges_perc_np)
        percentage_gap = 0.75
        adjusted_bin_widths_perc_np = full_bin_widths_perc_np - percentage_gap
        adjusted_bin_widths_perc_np = np.maximum(adjusted_bin_widths_perc_np, full_bin_widths_perc_np * 0.1)
        bin_widths_perc = adjusted_bin_widths_perc_np.tolist()

    return dict(
        travel_mids_mm=bin_mids_mm,
        travel_mids_perc=bin_mids_perc,
        time_perc=hist.tolist(),
        bin_widths_perc=bin_widths_perc
    )

def _selection_travel_stats(
    selected_strokes: Strokes,
    travel_data: list[float],
    linkage_max_travel_mm: float,
    selection_start_abs_index: int
) -> Tuple[float, float, float, int, float, float, float]:
    travel_values = []
    bottomouts_count = 0

    for s in (selected_strokes.Compressions or []) + (selected_strokes.Rebounds or []):
        if hasattr(s, 'Start') and s.Start is not None and \
           hasattr(s, 'End') and s.End is not None:
            
            rel_stroke_start = s.Start - selection_start_abs_index
            rel_stroke_end = s.End - selection_start_abs_index 

            eff_rel_start = max(0, rel_stroke_start)
            eff_rel_end = min(len(travel_data), rel_stroke_end + 1)

            if eff_rel_start < eff_rel_end:
                travel_values.extend(travel_data[eff_rel_start:eff_rel_end])
                
    if not travel_values:
        return (0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
    
    arr = np.array(travel_values)
    if arr.size == 0:
        return (0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)

    avg_mm = np.mean(arr)
    mx_mm = np.max(arr)
    p95_mm = np.percentile(arr, 95) if arr.size > 0 else 0.0
    
    avg_perc = to_percentage(avg_mm, linkage_max_travel_mm)
    mx_perc = to_percentage(mx_mm, linkage_max_travel_mm)
    p95_perc = to_percentage(p95_mm, linkage_max_travel_mm)
    
    return avg_mm, mx_mm, p95_mm, int(bottomouts_count), avg_perc, mx_perc, p95_perc

def _add_travel_stat_labels_stats(
    avg_mm_val: float, mx_mm_val: float, p95_mm_val: float,
    avg_perc_val: float, mx_perc_val: float, p95_perc_val: float,
    bottomouts_count: int,
    axis_max_travel_perc: float,
    y_range_start: float, y_range_end: float, p: figure
):
    span_line_color = '#FFD700'
    if np.isfinite(avg_perc_val):
        s_avg = Span(name='s_avg', location=avg_perc_val, dimension='height', line_color=span_line_color, line_dash='dashed', line_width=2)
        p.add_layout(s_avg)
    if np.isfinite(mx_perc_val):
        s_max = Span(name='s_max', location=mx_perc_val, dimension='height', line_color=span_line_color, line_dash='dashed', line_width=2)
        p.add_layout(s_max)
    if np.isfinite(p95_perc_val):
        s_p95 = Span(name='s_p95', location=p95_perc_val, dimension='height', line_color=span_line_color, line_dash='dashed', line_width=2)
        p.add_layout(s_p95)
    
    vertical_font_size_px = 12
    vertical_text_props_short = {
        'x_units': 'data', 'y_units': 'data',
        'text_font_size': f'{vertical_font_size_px}px', 'text_color': '#FFD700',
        'angle': np.pi / 2, 'text_align': 'center', 'text_baseline': 'middle',
    }
    label_x_offset_vertical = -10
    y_axis_height = abs(y_range_end - y_range_start)
    buffer_from_top_for_center = y_axis_height * 0.1
    vertical_label_y_pos = y_range_end - buffer_from_top_for_center
    min_y_label_pos = y_range_start + buffer_from_top_for_center
    vertical_label_y_pos = max(vertical_label_y_pos, min_y_label_pos)
    vertical_label_y_pos = min(vertical_label_y_pos, y_range_end - (y_axis_height * 0.03))

    if np.isfinite(avg_perc_val):
        l_avg_short = Label(name='l_avg_short', x=avg_perc_val, y=vertical_label_y_pos, text="avg",
                            x_offset=label_x_offset_vertical, y_offset=0, **vertical_text_props_short)
        p.add_layout(l_avg_short)
    if np.isfinite(mx_perc_val):
        l_max_short = Label(name='l_max_short', x=mx_perc_val, y=vertical_label_y_pos, text="max",
                            x_offset=label_x_offset_vertical, y_offset=0, **vertical_text_props_short)
        p.add_layout(l_max_short)
    if np.isfinite(p95_perc_val):
        l_p95_short = Label(name='l_p95_short', x=p95_perc_val, y=vertical_label_y_pos, text="95th",
                            x_offset=label_x_offset_vertical, y_offset=0, **vertical_text_props_short)
        p.add_layout(l_p95_short)

    col1_width = 6
    col2_width = 7
    col3_width = 10
    line1 = f"{'Avg:':<{col1_width}}{f'{avg_perc_val:.1f}%' if np.isfinite(avg_perc_val) else 'N/A':<{col2_width}} {f'({avg_mm_val:.1f} mm)' if np.isfinite(avg_mm_val) else '(N/A mm)':>{col3_width}}"
    line2 = f"{'95th:':<{col1_width}}{f'{p95_perc_val:.1f}%' if np.isfinite(p95_perc_val) else 'N/A':<{col2_width}} {f'({p95_mm_val:.1f} mm)' if np.isfinite(p95_mm_val) else '(N/A mm)':>{col3_width}}"
    line3 = f"{'Max:':<{col1_width}}{f'{mx_perc_val:.1f}%' if np.isfinite(mx_perc_val) else 'N/A':<{col2_width}} {f'({mx_mm_val:.1f} mm)' if np.isfinite(mx_mm_val) else '(N/A mm)':>{col3_width}}"
    empty_col3 = ' ' * (col3_width + 1)
    line4 = f"{'#BO:':<{col1_width}}{f'{bottomouts_count}':<{col2_width}}{empty_col3}"
    textbox_text = f"{line1}\n{line2}\n{line3}\n{line4}"
    textbox_y_center = (y_range_start + y_range_end) / 2.0
    textbox_x_start = axis_max_travel_perc * 0.6
    
    stats_textbox = Label(
        name='stats_textbox',
        x=textbox_x_start,
        y=textbox_y_center,
        x_units='data', y_units='data',
        text=textbox_text,
        text_font_size='12px',
        text_font='monospace',
        text_color='#FFD700',
        text_align='left',
        text_baseline='middle',
        x_offset=5,
        y_offset=-15,
        background_fill_color='#282828',
        background_fill_alpha=0.9,
        border_line_color=None,
        border_line_alpha=0.8,
        border_line_width=1,
    )
    p.add_layout(stats_textbox)

def travel_histogram_figure(
    telemetry_suspension: Suspension,
    linkage_max_travel_mm: float,
    color: tuple[str, ...],
    title: str
) -> figure:
    bins_mm = telemetry_suspension.TravelBins
    strokes_data = telemetry_suspension.Strokes
    travel_data = telemetry_suspension.Travel 
    
    hist_data = _travel_histogram_data(strokes_data, bins_mm, linkage_max_travel_mm)
    current_max_time_perc = 0.0
    if hist_data.get('time_perc') and len(hist_data['time_perc']) > 0:
        current_max_time_perc = np.max(hist_data['time_perc'])
    
    y_range_top = HISTOGRAM_RANGE_MULTIPLIER * (current_max_time_perc if current_max_time_perc > 0 else 1.0)
    
    p = figure(
        title=title,
        min_height=300,
        min_border_left=70,
        min_border_right=50,
        x_range=(0, 100),
        y_range=(0, y_range_top),
        sizing_mode="stretch_both",
        x_axis_label="Travel (%)",
        y_axis_label="Time (%)",
        toolbar_location='above',
        tools='xpan,xwheel_zoom,reset',
        active_drag='xpan',
        output_backend='webgl')
    
    p.xaxis.ticker = np.arange(0, 101, 10)
    
    if hist_data.get('travel_mids_perc') and len(hist_data['travel_mids_perc']) > 0 and \
       hist_data.get('bin_widths_perc') and len(hist_data['bin_widths_perc']) == len(hist_data['travel_mids_perc']):
        source_data = {
            'travel_mids_perc': hist_data['travel_mids_perc'],
            'time_perc': hist_data['time_perc'],
            'bar_widths_perc': hist_data['bin_widths_perc']
        }
        p.vbar(x='travel_mids_perc', width='bar_widths_perc', top='time_perc', bottom=0,
               source=ColumnDataSource(name='ds_hist', data=source_data),
               line_width=2, color=color, fill_alpha=0.4)
               
    y_start = p.y_range.start if p.y_range and p.y_range.start is not None else 0.0
    y_end = p.y_range.end if p.y_range and p.y_range.end is not None else 1.0
    
    avg_mm_val, mx_mm_val, p95_mm_val, bottomouts_count, \
    avg_perc_val, mx_perc_val, p95_perc_val = _selection_travel_stats(
        strokes_data,
        travel_data, # Full travel data for initial plot
        linkage_max_travel_mm,
        0 # selection_start_abs_index is 0 for the initial full data plot
    )
    
    _add_travel_stat_labels_stats(
        avg_mm_val, mx_mm_val, p95_mm_val,
        avg_perc_val, mx_perc_val, p95_perc_val,
        bottomouts_count,
        100.0, 
        y_start, y_end, p
    )
    
    if p.legend:
        p.legend.location = "top_right"
        p.legend.click_policy = "hide"
    return p

def update_travel_histogram(
    selected_strokes: Strokes,
    travel_data: list[float],
    bins_mm: list[float],
    linkage_max_travel_mm: float,
    selection_start_abs_index: int
):
    hist_data_selected = _travel_histogram_data(selected_strokes, bins_mm, linkage_max_travel_mm)
    current_max_time_perc = 0.0
    if hist_data_selected.get('time_perc') and len(hist_data_selected['time_perc']) > 0:
        current_max_time_perc = np.max(hist_data_selected['time_perc'])
    
    range_end_val = HISTOGRAM_RANGE_MULTIPLIER * (current_max_time_perc if current_max_time_perc > 0 else 1.0)
    
    avg_mm, mx_mm, p95_mm, bottomouts, avg_perc, mx_perc, p95_perc = _selection_travel_stats(
        selected_strokes,
        travel_data,
        linkage_max_travel_mm,
        selection_start_abs_index
    )
    
    # Adjusted column widths and formatting to match _add_travel_stat_labels_stats
    col1_width = 6
    col2_width = 7
    col3_width = 10
    empty_col3 = ' ' * (col3_width + 1) # Ensure this aligns with col3_width for spacing

    line1 = f"{'Avg:':<{col1_width}}{f'{avg_perc:.1f}%' if np.isfinite(avg_perc) else 'N/A':<{col2_width}} {f'({avg_mm:.1f} mm)' if np.isfinite(avg_mm) else '(N/A mm)':>{col3_width}}"
    line2 = f"{'95th:':<{col1_width}}{f'{p95_perc:.1f}%' if np.isfinite(p95_perc) else 'N/A':<{col2_width}} {f'({p95_mm:.1f} mm)' if np.isfinite(p95_mm) else '(N/A mm)':>{col3_width}}"
    line3 = f"{'Max:':<{col1_width}}{f'{mx_perc:.1f}%' if np.isfinite(mx_perc) else 'N/A':<{col2_width}} {f'({mx_mm:.1f} mm)' if np.isfinite(mx_mm) else '(N/A mm)':>{col3_width}}"
    # Changed "Bottomouts:" to "#BO:" and ensured `bottomouts` (which is an int) is formatted correctly within col2_width
    line4 = f"{'#BO:':<{col1_width}}{f'{bottomouts}':<{col2_width}}{empty_col3}"
    full_textbox_text = f"{line1}\n{line2}\n{line3}\n{line4}"
    
    source_update_data = {
        'travel_mids_perc': hist_data_selected['travel_mids_perc'],
        'time_perc': hist_data_selected['time_perc'],
        'bar_widths_perc': hist_data_selected['bin_widths_perc']
    }
    
    update_dict = dict(
        source_data=source_update_data,
        range_end=range_end_val,
        avg=avg_perc,
        mx=mx_perc,
        p95=p95_perc,
        stats_textbox_text=full_textbox_text # Use the new formatted text
    )
    return update_dict

def travel_figure(telemetry: Telemetry, lod: int,
                  front_color: tuple[str, ...], rear_color: tuple[str, ...]) -> figure:
    length = len(telemetry.Front.Travel if telemetry.Front.Present else
                 telemetry.Rear.Travel)

    time_data: np.ndarray
    tf_lod_data: np.ndarray
    tr_lod_data: np.ndarray
    fr_data: np.ndarray
    rr_data: np.ndarray

    if length <= 0 or telemetry.SampleRate <= 0:
        time_data = np.array([0.0])
        tf_lod_data = np.array([0.0])
        tr_lod_data = np.array([0.0])
        fr_data = np.array([0.0])
        rr_data = np.array([0.0])
    else:
        num_time_points = max(1, (length -1) // lod + 1)
        time_data = np.around(np.linspace(0, (length -1) / telemetry.SampleRate, num_time_points, endpoint=True), 4)

        front_max_mm = telemetry.Linkage.MaxFrontTravel
        rear_max_mm = telemetry.Linkage.MaxRearTravel

        if telemetry.Front.Present and len(telemetry.Front.Travel) > 0:
            source_data_len = len(telemetry.Front.Travel[::lod])
            valid_len = min(source_data_len, num_time_points)

            temp_tf_lod = np.around(telemetry.Front.Travel[::lod][:valid_len], 4)
            tf_lod_data = np.full(num_time_points, 0.0)
            tf_lod_data[:valid_len] = temp_tf_lod

            fr_data = np.full(num_time_points, 0.0)
            if front_max_mm is not None and front_max_mm > 0:
                 fr_data[:valid_len] = np.around(tf_lod_data[:valid_len] / front_max_mm * 100, 1)
        else:
            tf_lod_data = np.full(num_time_points, 0.0)
            fr_data = np.full(num_time_points, 0.0)

        if telemetry.Rear.Present and len(telemetry.Rear.Travel) > 0:
            source_data_len_rear = len(telemetry.Rear.Travel[::lod])
            valid_len_rear = min(source_data_len_rear, num_time_points)

            temp_tr_lod = np.around(telemetry.Rear.Travel[::lod][:valid_len_rear], 4)
            tr_lod_data = np.full(num_time_points, 0.0)
            tr_lod_data[:valid_len_rear] = temp_tr_lod

            rr_data = np.full(num_time_points, 0.0)
            if rear_max_mm is not None and rear_max_mm > 0:
                rr_data[:valid_len_rear] = np.around(tr_lod_data[:valid_len_rear] / rear_max_mm * 100, 1)
        else:
            tr_lod_data = np.full(num_time_points, 0.0)
            rr_data = np.full(num_time_points, 0.0)

    current_len = len(time_data)
    if len(tf_lod_data) != current_len: tf_lod_data = np.full(current_len, 0.0)
    if len(tr_lod_data) != current_len: tr_lod_data = np.full(current_len, 0.0)
    if len(fr_data) != current_len: fr_data = np.full(current_len, 0.0)
    if len(rr_data) != current_len: rr_data = np.full(current_len, 0.0)

    source = ColumnDataSource(name='ds_travel', data=dict(
        t=time_data,
        f=tf_lod_data,
        r=tr_lod_data,
        fr=fr_data,
        rr=rr_data
    ))

    max_travel_possible_front = telemetry.Linkage.MaxFrontTravel if telemetry.Linkage.MaxFrontTravel is not None else 0
    max_travel_possible_rear = telemetry.Linkage.MaxRearTravel if telemetry.Linkage.MaxRearTravel is not None else 0

    y_axis_upper_bound = 0
    if len(tf_lod_data) > 0 and len(tr_lod_data) > 0 :
        data_max_travel = max(np.max(tf_lod_data) if len(tf_lod_data) > 0 else 0,
                              np.max(tr_lod_data) if len(tr_lod_data) > 0 else 0)
        theoretical_max_travel = max(max_travel_possible_front, max_travel_possible_rear)

        if theoretical_max_travel > data_max_travel and theoretical_max_travel > 0:
             y_axis_upper_bound = theoretical_max_travel * 1.05
        elif data_max_travel > 0:
             y_axis_upper_bound = data_max_travel * 1.05
        else:
            y_axis_upper_bound = 10 

    y_axis_lower_bound = - (y_axis_upper_bound * 0.05) 

    p = figure(
        name='travel',
        title="Wheel travel",
        height=400,
        min_border_left=50,
        min_border_right=50,
        sizing_mode="stretch_width",
        toolbar_location='above',
        tools='xpan,reset,hover',
        active_inspect=None,
        active_drag='xpan',
        tooltips=[
            ("elapsed time", "@t s"),
            ("front wheel", "@fr{0.0}% (@f{0.0} mm)"),
            ("rear wheel", "@rr{0.0}% (@r{0.0} mm)")
        ],
        x_axis_label="Elapsed time (s)",
        y_axis_label="Travel (mm)",
        y_range=Range1d(y_axis_upper_bound, y_axis_lower_bound), 
        output_backend='webgl')
    
    p.yaxis.ticker = SingleIntervalTicker(interval=20)

    if callable(globals().get('_add_airtime_labels')):
        _add_airtime_labels(p, telemetry.Airtimes)

    p.x_range = Range1d(0, time_data[-1] if len(time_data) > 0 else 1.0, bounds='auto')

    line_front = p.line(
        't', 'f',
        legend_label="Front",
        line_width=2,
        color=front_color,
        source=source)

    line_rear = p.line(
        't', 'r',
        legend_label="Rear",
        line_width=2,
        color=rear_color,
        source=source)
    p.legend.level = 'overlay'

    x_start_range = p.x_range.start if p.x_range and p.x_range.start is not None else 0
    x_end_range = p.x_range.end if p.x_range and p.x_range.end is not None else 1.0

    initial_x_end = time_data[-1] if len(time_data) > 0 else 1.0

    left_unselected = BoxAnnotation(name='left_unselected_travel',
        left=x_start_range, right=x_start_range, fill_alpha=0.8, fill_color='#000000')
    right_unselected = BoxAnnotation(name='right_unselected_travel',
        left=x_end_range, right=x_end_range, fill_alpha=0.8, fill_color='#000000')
    p.add_layout(left_unselected)
    p.add_layout(right_unselected)

    bs = BoxSelectTool(dimensions="width", name='time_box_select')
    p.add_tools(bs)

    p.js_on_event(
        DoubleTap,
        CustomJS(
            args=dict(lu=left_unselected, ru=right_unselected, end=initial_x_end),
            code='''
                 lu.right = 0;
                 ru.left = end;
                 if (typeof SST !== 'undefined' && SST.update && SST.update.plots) SST.update.plots(-1, -1);
                 '''))
    p.js_on_event(
        SelectionGeometry,
        CustomJS(
            args=dict(lu=left_unselected, ru=right_unselected),
            code='''
                 const geometry = cb_obj['geometry'];
                 if (geometry && geometry.x0 != null && geometry.x1 != null) {
                    lu.right = geometry['x0'];
                    ru.left = geometry['x1'];
                    if (typeof SST !== 'undefined' && SST.update && SST.update.plots) SST.update.plots(geometry['x0'], geometry['x1']);
                 }
                 '''))

    wz = WheelZoomTool(maintain_focus=False, dimensions='width')
    p.add_tools(wz)
    p.toolbar.active_scroll = wz

    s_current_time = Span(name='s_current_time', location=0, dimension='height', line_color='#d0d0d0')
    ch = CrosshairTool(dimensions='height', line_color='#d0d0d0', overlay=s_current_time)
    p.add_tools(ch)
    p.toolbar.active_inspect = ch

    p.hover.mode = 'vline'
    p.hover.line_policy = 'none'
    p.hover.show_arrow = False
    p.hover.renderers = [line_front, line_rear]
    p.legend.location = 'bottom_right'
    p.legend.click_policy = 'hide'
    return p

def _add_airtime_labels(p_travel: figure, airtimes: List[Airtime]):
    if airtimes is None: return
    for airtime in airtimes:
        b = BoxAnnotation(
            left=airtime.Start, right=airtime.End, fill_color=Spectral11[-2], fill_alpha=0.2,
            movable='none', resizable='none', propagate_hover=True)
        p_travel.add_layout(b)
        airtime_text = f"airtime: {airtime.End-airtime.Start:.1f} s"
        label_x_pos = airtime.Start + (airtime.End - airtime.Start) / 2 if airtime.End > airtime.Start else airtime.Start
        airtime_label = Label(
            x=label_x_pos, y=30, x_units='data', y_units='screen',
            text_font_size='14px', text_color='#fefefe', text_align='center', text=airtime_text)
        p_travel.add_layout(airtime_label)