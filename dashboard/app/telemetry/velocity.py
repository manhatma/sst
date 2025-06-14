import numpy as np
from typing import Any, Tuple, List, Optional

from bokeh import events # type: ignore
from bokeh.models import ColumnDataSource # type: ignore
from bokeh.models.annotations import BoxAnnotation, ColorBar, Label, Span # type: ignore
from bokeh.models.callbacks import CustomJS # type: ignore
from bokeh.models.formatters import PrintfTickFormatter # type: ignore
from bokeh.models.mappers import LinearColorMapper # type: ignore
from bokeh.models.ranges import Range1d # type: ignore
from bokeh.models.tickers import FixedTicker, SingleIntervalTicker # type: ignore
from bokeh.models.tools import WheelZoomTool, CrosshairTool # type: ignore
from bokeh.palettes import Spectral11 # type: ignore
from bokeh.plotting import figure # type: ignore
from scipy.stats import norm
from flask import current_app # type: ignore

try:
    from app.telemetry.psst import Strokes, Telemetry, Stroke, StrokeStat
except ImportError:
    class StrokeStat:
        SumVelocity: float = 0.0
        Count: int = 0
        MaxVelocity: float = 0.0

    class Stroke:
        Start: int = 0
        End: int = 0
        Stat: Optional[StrokeStat] = None
        DigitizedTravel: Optional[List[int]] = None
        DigitizedVelocity: Optional[List[int]] = None
        FineDigitizedVelocity: Optional[List[int]] = None

    class Strokes:
        Compressions: List[Stroke] = []
        Rebounds: List[Stroke] = []

    class SuspensionData:
        Velocity: List[float] = []
        Strokes: Optional[Strokes] = None # type: ignore
        TravelBins: List[float] = []
        VelocityBins: List[float] = []
        FineVelocityBins: List[float] = []
        Present: bool = False

    class Telemetry:
        Front: SuspensionData = SuspensionData()
        Rear: SuspensionData = SuspensionData()
        SampleRate: int = 100


TRAVEL_BINS_FOR_VELOCITY_HISTOGRAM = 10
HISTOGRAM_RANGE_MULTIPLIER = 1.5
HISTOGRAM_RANGE_HIGH = 2000
HISTOGRAM_RANGE_LOW = -HISTOGRAM_RANGE_HIGH


def velocity_figure(telemetry: Telemetry, lod: int,
                    front_color: str, rear_color: str) -> figure:
    length = len(telemetry.Front.Velocity if telemetry.Front.Present and telemetry.Front.Velocity else
                 (telemetry.Rear.Velocity if telemetry.Rear.Present and telemetry.Rear.Velocity else []))

    if length <= 0:
        time_data = np.array([0.0])
        vf_lod_data = np.array([0.0])
        vr_lod_data = np.array([0.0])
    else:
        num_time_points = (length -1) // lod + 1 if length > 0 else 1
        if telemetry.SampleRate > 0:
            time_data = np.around(np.linspace(0, (length -1) / telemetry.SampleRate, num_time_points, endpoint=True), 4)
        else:
            time_data = np.arange(num_time_points, dtype=float)

        vf_source = telemetry.Front.Velocity if telemetry.Front.Present and telemetry.Front.Velocity else []
        vr_source = telemetry.Rear.Velocity if telemetry.Rear.Present and telemetry.Rear.Velocity else []

        vf_lod_data = np.full(len(time_data), 0.0)
        if telemetry.Front.Present and len(vf_source) > 0:
             actual_lod_data = np.around(np.array(vf_source[::lod]), 4) / 1000
             take_len = min(len(actual_lod_data), len(time_data))
             vf_lod_data[:take_len] = actual_lod_data[:take_len]

        vr_lod_data = np.full(len(time_data), 0.0)
        if telemetry.Rear.Present and len(vr_source) > 0:
            actual_lod_data_rear = np.around(np.array(vr_source[::lod]), 4) / 1000
            take_len_rear = min(len(actual_lod_data_rear), len(time_data))
            vr_lod_data[:take_len_rear] = actual_lod_data_rear[:take_len_rear]

    if len(time_data) == 0:
        time_data = np.array([0.0])
        vf_lod_data = np.array([0.0])
        vr_lod_data = np.array([0.0])

    source = ColumnDataSource(name='ds_velocity', data=dict(
        t=time_data,
        f=vf_lod_data,
        r=vr_lod_data,
    ))
    p = figure(
        name='velocity',
        title="Suspension velocity",
        height=275,
        min_border_left=50,
        min_border_right=50,
        sizing_mode="stretch_width",
        toolbar_location='above',
        tools='xpan,reset,hover,crosshair', 
        # active_inspect=None,
        active_drag='xpan',
        tooltips=[("elapsed time", "@t{0.000} s"),
                  ("front wheel", "@f{0.000} m/s"),
                  ("rear wheel", "@r{0.000} m/s")],
        x_axis_label="Elapsed time (s)",
        y_axis_label="Velocity (m/s)",
        output_backend='webgl')

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

    if p.legend:
        p.legend.level = 'overlay'
        p.legend.location = 'top_right'
        p.legend.click_policy = 'hide'

    wz = WheelZoomTool(maintain_focus=False, dimensions='width')
    p.add_tools(wz)
    p.toolbar.active_scroll = wz

    # Create Span for CrosshairTool overlay, similar to travel.py
    s_current_time_velocity = Span(name='s_current_time_velocity',
                                   location=0,
                                   dimension='height',
                                   line_color='#d0d0d0')
    # Create CrosshairTool with the overlay
    ch_velocity = CrosshairTool(dimensions='height',
                                line_color='#d0d0d0',
                                overlay=s_current_time_velocity)
    p.add_tools(ch_velocity)
    # Set CrosshairTool as active_inspect
    p.toolbar.active_inspect = ch_velocity

    # Configure HoverTool
    p.hover.mode = 'vline'
    p.hover.line_policy = 'none'  # Set to 'none' as in travel.py to avoid conflicting lines
    p.hover.show_arrow = False
    p.hover.renderers = [line_front, line_rear] # As per previous modification

    return p


def _normal_distribution_data(strokes: Optional[Strokes], velocity_data: list[float],
                              step: float) -> dict[str, Any]:
    stroke_velocity_points = []
    if strokes and velocity_data:
        all_s_list = (strokes.Compressions if strokes.Compressions else []) + \
                     (strokes.Rebounds if strokes.Rebounds else [])
        for s in all_s_list:
            if not (s and hasattr(s, 'Start') and hasattr(s, 'End')): continue
            if s.Start < 0 or s.End >= len(velocity_data) or s.Start > s.End: continue
            stroke_velocity_points.extend(velocity_data[s.Start:s.End+1])

    if not stroke_velocity_points:
        return dict(pdf=[].tolist(), ny=[].tolist())

    stroke_velocity_np = np.array(stroke_velocity_points)
    mu, std = norm.fit(stroke_velocity_np)

    min_vel = stroke_velocity_np.min() if stroke_velocity_np.size > 0 else 0.0
    max_vel = stroke_velocity_np.max() if stroke_velocity_np.size > 0 else 0.0

    if abs(min_vel - max_vel) < 1e-9:
        ny_val = np.array([min_vel])
        pdf_val = np.array([1.0 * step * 100]) if std == 0 and ny_val.size > 0 else np.array([0.0])
    else:
        num_points = 100
        if max_vel > min_vel :
             ny_val = np.linspace(min_vel, max_vel, num_points)
             pdf_val = norm.pdf(ny_val, mu, std) * step * 100 if std > 1e-9 else np.zeros_like(ny_val)
        else:
            ny_val = np.array([min_vel])
            pdf_val = np.array([1.0 * step * 100]) if std == 0 else np.array([0.0])

    return dict(pdf=pdf_val.tolist(), ny=ny_val.tolist())


def _velocity_histogram_data(strokes: Optional[Strokes], hst: int, tbins: list[float],
                             vbins: list[float], vbins_fine: list[float]) -> Tuple[
                             dict[str, Any], dict[str, Any], float, float]:
    step = vbins[1] - vbins[0] if vbins and len(vbins) > 1 else 1.0
    step_lowspeed = vbins_fine[1] - vbins_fine[0] if vbins_fine and len(vbins_fine) > 1 else 1.0

    num_travel_bins_for_hist = TRAVEL_BINS_FOR_VELOCITY_HISTOGRAM
    if not tbins or len(tbins) <=1 :
        divider = 1
        num_travel_bins_for_hist = 1
    else:
        divider = max(1, (len(tbins) - 1) // num_travel_bins_for_hist)

    hist_shape_v = len(vbins) - 1 if vbins and len(vbins) > 1 else 1
    hist_shape_v_fine = len(vbins_fine) -1 if vbins_fine and len(vbins_fine) > 1 else 1

    hist = np.zeros((num_travel_bins_for_hist, hist_shape_v))
    hist_lowspeed = np.zeros((num_travel_bins_for_hist, hist_shape_v_fine))
    total_count = 0

    all_s_list = []
    if strokes:
        all_s_list = (strokes.Compressions if strokes.Compressions else []) + \
                     (strokes.Rebounds if strokes.Rebounds else [])

    for s in all_s_list:
        if s and s.Stat and hasattr(s.Stat, 'Count') and s.Stat.Count > 0:
            total_count += s.Stat.Count
            if s.DigitizedTravel and s.DigitizedVelocity and s.FineDigitizedVelocity:
                iter_len = min(s.Stat.Count, len(s.DigitizedTravel), len(s.DigitizedVelocity), len(s.FineDigitizedVelocity))
                for i in range(iter_len):
                    if num_travel_bins_for_hist <= 0: continue

                    tbin_idx_val = s.DigitizedTravel[i]
                    tbin_idx = min(max(0, tbin_idx_val // divider if divider > 0 else 0), num_travel_bins_for_hist - 1)

                    if hist_shape_v > 0:
                        vbin_idx_val = s.DigitizedVelocity[i]
                        vbin_idx = min(max(0, vbin_idx_val), hist_shape_v - 1)
                        hist[tbin_idx][vbin_idx] += 1

                    if hist_shape_v_fine > 0:
                        vbin_fine_idx_val = s.FineDigitizedVelocity[i]
                        vbin_fine_idx = min(max(0, vbin_fine_idx_val), hist_shape_v_fine - 1)

                        if vbins_fine and 0 <= vbin_fine_idx < len(vbins_fine) -1:
                           current_vfine_val = (vbins_fine[vbin_fine_idx] + vbins_fine[vbin_fine_idx+1]) / 2
                           if -(hst + step_lowspeed/2) < current_vfine_val < (hst + step_lowspeed/2):
                                hist_lowspeed[tbin_idx][vbin_fine_idx] += 1
    if total_count > 0:
        hist = hist / total_count * 100.0
        hist_lowspeed = hist_lowspeed / total_count * 100.0

    largest_bin = np.max(np.sum(hist, axis=0)) if hist.size > 0 else 0.0
    largest_bin_lowspeed = np.max(np.sum(hist_lowspeed, axis=0)) if hist_lowspeed.size > 0 else 0.0

    sd = {str(k_idx): v.tolist() for k_idx, v in enumerate(hist)}
    sd['y'] = ((np.array(vbins[:-1]) + step / 2).tolist() if vbins and len(vbins) > 1 else [0.0])

    sd_lowspeed = {str(k_idx): v.tolist() for k_idx, v in enumerate(hist_lowspeed)}
    sd_lowspeed['y'] = ((np.array(vbins_fine[:-1]) + step_lowspeed / 2).tolist() if vbins_fine and len(vbins_fine) > 1 else [0.0])

    return (sd, sd_lowspeed,
            HISTOGRAM_RANGE_MULTIPLIER * largest_bin if largest_bin > 0 else 1.0,
            HISTOGRAM_RANGE_MULTIPLIER * largest_bin_lowspeed if largest_bin_lowspeed > 0 else 1.0)


def velocity_histogram_figure(strokes: Optional[Strokes], velocity_data: list[float],
                              tbins: list[float], vbins: list[float],
                              vbins_fine: list[float], hst: int,
                              title: str, title_lowspeed: str) -> Tuple[figure, figure]:
    step = vbins[1] - vbins[0] if vbins and len(vbins) > 1 else 1.0
    step_lowspeed = vbins_fine[1] - vbins_fine[0] if vbins_fine and len(vbins_fine) > 1 else 1.0

    sd, sd_lowspeed, mx, mx_lowspeed = _velocity_histogram_data(
        strokes, hst, tbins, vbins, vbins_fine)
    source = ColumnDataSource(name='ds_hist', data=sd)
    source_lowspeed = ColumnDataSource(name='ds_hist_lowspeed', data=sd_lowspeed)

    y_range_main = (HISTOGRAM_RANGE_HIGH, HISTOGRAM_RANGE_LOW)
    y_range_lowspeed_abs = hst + 100
    y_range_lowspeed = (y_range_lowspeed_abs, -y_range_lowspeed_abs)

    p = figure(
        title=title,
        height=600,
        sizing_mode='stretch_width',
        x_range=(0, mx),
        y_range=y_range_main,
        x_axis_label="Time (%)",
        y_axis_label='Speed (mm/s)',
        toolbar_location='above',
        tools='ypan,ywheel_zoom,reset',
        active_drag='ypan',
        output_backend='webgl')
    p.yaxis[0].formatter = PrintfTickFormatter(format="%5d")
    palette = Spectral11[1:]
    k_val = [key for key in sd.keys() if key != 'y']
    if k_val and 'y' in sd and sd.get('y') and sd['y'] and len(sd['y']) > 0 and sd['y'][0] is not None:
        p.hbar_stack(stackers=k_val, name='hb_vhist_main', y='y', height=step,
                     color=palette, line_color='black', fill_alpha=0.8,
                     source=source)

    source_normal = ColumnDataSource(
        name='ds_normal',
        data=_normal_distribution_data(strokes, velocity_data, step))
    if source_normal.data.get('pdf') and len(source_normal.data['pdf']) > 0 and \
       source_normal.data.get('ny') and len(source_normal.data['ny']) > 0:
        p.line(x='pdf', y='ny', name='line_normal_main', line_width=2, source=source_normal,
               line_dash='dashed', color=Spectral11[-2])

    p_lowspeed = figure(
        title=title_lowspeed,
        height=600,
        max_width=250,
        sizing_mode='stretch_width',
        x_range=(0, mx_lowspeed),
        y_range=y_range_lowspeed,
        x_axis_label="Time (%)",
        y_axis_label='Speed (mm/s)',
        toolbar_location=None,
        tools='',
        output_backend='webgl')
    p_lowspeed.yaxis[0].formatter = PrintfTickFormatter(format="%5d")
    k_lowspeed_val = [key for key in sd_lowspeed.keys() if key != 'y']
    if k_lowspeed_val and 'y' in sd_lowspeed and sd_lowspeed.get('y') and sd_lowspeed['y'] and len(sd_lowspeed['y']) > 0 and sd_lowspeed['y'][0] is not None:
        p_lowspeed.hbar_stack(stackers=k_lowspeed_val, name='hb_vhist_lowspeed', y='y',
                              height=step_lowspeed, color=palette,
                              line_color='black', fill_alpha=0.8,
                              source=source_lowspeed)
    p_lowspeed.xaxis.ticker = SingleIntervalTicker(interval=max(1.0, mx_lowspeed // 5 if mx_lowspeed > 5 else 1.0))

    source_normal_lowspeed = ColumnDataSource(
        name='ds_normal_lowspeed',
        data=_normal_distribution_data(strokes, velocity_data, step_lowspeed))
    if source_normal_lowspeed.data.get('pdf') and len(source_normal_lowspeed.data['pdf']) > 0 and \
       source_normal_lowspeed.data.get('ny') and len(source_normal_lowspeed.data['ny']) > 0:
        p_lowspeed.line(x='pdf', y='ny', name='line_normal_lowspeed', line_width=2,
                        source=source_normal_lowspeed,
                        line_dash='dashed', color=Spectral11[-2])

    mapper = LinearColorMapper(palette=palette, low=0, high=100)
    color_bar = ColorBar(name='color_bar_vhist',
        color_mapper=mapper,
        height=8,
        title="Travel (%)",
        ticker=FixedTicker(ticks=list(np.arange(0, 101, 10))))
    p.add_layout(color_bar, 'above')
    p_lowspeed.add_layout(ColorBar(name='color_bar_vhist_lowspeed', color_mapper=mapper, height=8, title="Travel (%)", ticker=FixedTicker(ticks=list(np.arange(0, 101, 10)))), 'above')

    lowspeed_box = BoxAnnotation(name='box_lowspeed_highlight',
        top=hst, bottom=-hst,
        left=0, level='underlay', fill_alpha=0.1, fill_color='#FFFFFF'
    )
    p.add_layout(lowspeed_box)
    _add_velocity_stat_labels(p, strokes, mx, velocity_data)


    js_code_label_update = """
        // This JS code is currently empty as its previous version was complex and might need
        // careful review if labels are not updating their y-positions correctly upon zoom/pan.
        // For now, we rely on the Python-side positioning during creation and update.
        // const main_plot = p; // p is passed in args
        // Example: main_plot.select_one({name: 'l_short_maxr'}).y = new_calculated_y;
    """
    p.js_on_event(events.Pan, CustomJS(args=dict(p=p), code=js_code_label_update))
    p.js_on_event(events.MouseWheel, CustomJS(args=dict(p=p), code=js_code_label_update))

    return p, p_lowspeed

def _add_velocity_stat_labels(p: figure, strokes: Optional[Strokes], hist_max_x: float, all_velocities: List[float]):
    avgr, maxr, avgc, maxc, p95r_val, p95c_val = _velocity_stats(strokes, all_velocities)

    span_line_color = '#FFD700'

    def create_span(name, location, p_fig):
        if location is not None and np.isfinite(location):
            s = Span(name=name, location=location, dimension='width', line_color=span_line_color, line_dash='dashed', line_width=1)
            p_fig.add_layout(s)
        return None

    create_span('s_maxr', maxr, p)
    create_span('s_p95r', p95r_val, p)
    create_span('s_avgr', avgr, p)
    create_span('s_maxc', maxc, p)
    create_span('s_p95c', p95c_val, p)
    create_span('s_avgc', avgc, p)

    short_label_text_props = {
        'x': hist_max_x if hist_max_x > 0 and np.isfinite(hist_max_x) else 1.0,
        'x_units': 'data',
        'y_units': 'data',
        'text_font_size': '12px',
        'text_color': '#FFD700',
        'text_align': 'right',
        'text_baseline': 'middle',
        'x_offset': -5
    }
    y_offset_short_label_pixels = 7

    short_labels_data = [
        {'name': 'l_short_maxr', 'y': maxr, 'text': "Max Reb", 'y_offset': y_offset_short_label_pixels},
        {'name': 'l_short_p95r', 'y': p95r_val, 'text': "P95 Reb", 'y_offset': y_offset_short_label_pixels},
        {'name': 'l_short_avgr', 'y': avgr, 'text': "Avg Reb", 'y_offset': y_offset_short_label_pixels},
        {'name': 'l_short_avgc', 'y': avgc, 'text': "Avg Comp", 'y_offset': -y_offset_short_label_pixels},
        {'name': 'l_short_p95c', 'y': p95c_val, 'text': "P95 Comp", 'y_offset': -y_offset_short_label_pixels},
        {'name': 'l_short_maxc', 'y': maxc, 'text': "Max Comp", 'y_offset': -y_offset_short_label_pixels},
    ]

    for data in short_labels_data:
        if data['y'] is not None and np.isfinite(data['y']):
            current_props = short_label_text_props.copy()
            p.add_layout(Label(name=data['name'], y=data['y'], text=data['text'],
                               y_offset=data['y_offset'], **current_props))

    na_str = "N/A"
    maxr_txt = f"{maxr:.0f}" if maxr is not None and np.isfinite(maxr) else na_str
    p95r_txt = f"{p95r_val:.0f}" if p95r_val is not None and np.isfinite(p95r_val) else na_str
    avgr_txt = f"{avgr:.0f}" if avgr is not None and np.isfinite(avgr) else na_str
    avgc_txt = f"{avgc:.0f}" if avgc is not None and np.isfinite(avgc) else na_str
    p95c_txt = f"{p95c_val:.0f}" if p95c_val is not None and np.isfinite(p95c_val) else na_str
    maxc_txt = f"{maxc:.0f}" if maxc is not None and np.isfinite(maxc) else na_str

    col_width = 7

    textbox_content = (
        f"Max Reb:  {maxr_txt:>{col_width}} mm/s\n"
        f"P95 Reb:  {p95r_txt:>{col_width}} mm/s\n"
        f"Avg Reb:  {avgr_txt:>{col_width}} mm/s\n \n"
        f"Avg Comp: {avgc_txt:>{col_width}} mm/s\n"
        f"P95 Comp: {p95c_txt:>{col_width}} mm/s\n"
        f"Max Comp: {maxc_txt:>{col_width}} mm/s"
    )

    y_range_start_val = p.y_range.start if p.y_range and p.y_range.start is not None and np.isfinite(p.y_range.start) else HISTOGRAM_RANGE_HIGH
    y_range_end_val = p.y_range.end if p.y_range and p.y_range.end is not None and np.isfinite(p.y_range.end) else HISTOGRAM_RANGE_LOW
    y_textbox_position = y_range_end_val + abs(y_range_start_val - y_range_end_val) * 0.05

    x_range_start_val = p.x_range.start if p.x_range and p.x_range.start is not None and np.isfinite(p.x_range.start) else 0.0
    x_range_end_val = p.x_range.end if p.x_range and p.x_range.end is not None and np.isfinite(p.x_range.end) else 1.0
    plot_x_center = (x_range_start_val + x_range_end_val) / 2.0

    textbox_label = Label(
        name='l_velocity_textbox',
        x=plot_x_center,
        y=y_textbox_position,
        x_units='data',
        y_units='data',
        text=textbox_content,
        text_font='monospace',
        text_font_size='12px',
        text_color='#FFD700',
        text_align='center',
        text_baseline='top',
        x_offset=0,
        y_offset=10,
        background_fill_color='#1E1E1E',
        background_fill_alpha=0.85,
        border_line_color="#444444",
        border_line_alpha=0.8,
        border_line_width=1
    )
    p.add_layout(textbox_label)


def _velocity_stats(strokes: Optional[Strokes], all_velocities_data: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    csum, ccount, maxc_val = 0.0, 0, None
    all_comp_vel_points = []
    if strokes and strokes.Compressions:
        for c in strokes.Compressions:
            if not (c and hasattr(c, 'Stat') and c.Stat and hasattr(c.Stat, 'MaxVelocity') and c.Stat.MaxVelocity is not None): continue
            csum += c.Stat.SumVelocity if c.Stat.SumVelocity is not None else 0
            ccount += c.Stat.Count if c.Stat.Count is not None else 0
            if maxc_val is None or (c.Stat.MaxVelocity is not None and c.Stat.MaxVelocity > maxc_val) :
                maxc_val = c.Stat.MaxVelocity
            if all_velocities_data and hasattr(c,'Start') and hasattr(c,'End') and \
               0 <= c.Start < len(all_velocities_data) and 0 <= c.End < len(all_velocities_data) and c.Start <= c.End:
                all_comp_vel_points.extend(v for v in all_velocities_data[c.Start:c.End+1] if v is not None and v > 0)

    avgc = csum / ccount if ccount > 0 else None
    p95c = float(np.percentile(all_comp_vel_points, 95)) if all_comp_vel_points else None

    rsum, rcount, maxr_val = 0.0, 0, None
    all_reb_vel_points_abs = []
    if strokes and strokes.Rebounds:
        for r in strokes.Rebounds:
            if not (r and hasattr(r, 'Stat') and r.Stat and hasattr(r.Stat, 'MaxVelocity') and r.Stat.MaxVelocity is not None): continue
            rsum += r.Stat.SumVelocity if r.Stat.SumVelocity is not None else 0
            rcount += r.Stat.Count if r.Stat.Count is not None else 0
            if maxr_val is None or (r.Stat.MaxVelocity is not None and r.Stat.MaxVelocity < maxr_val):
                maxr_val = r.Stat.MaxVelocity
            if all_velocities_data and hasattr(r,'Start') and hasattr(r,'End') and \
                0 <= r.Start < len(all_velocities_data) and 0 <= r.End < len(all_velocities_data) and r.Start <= r.End:
                 all_reb_vel_points_abs.extend(abs(v) for v in all_velocities_data[r.Start:r.End+1] if v is not None and v < 0)

    avgr = rsum / rcount if rcount > 0 else None
    p95r_mag = float(np.percentile(all_reb_vel_points_abs, 95)) if all_reb_vel_points_abs else None
    p95r = -p95r_mag if p95r_mag is not None else None

    return avgr, maxr_val, avgc, maxc_val, p95r, p95c


def _velocity_band_stats(strokes: Optional[Strokes], velocity_data: list[float],
                         high_speed_threshold: float) -> Tuple[float, float, float, float]:
    if not velocity_data: return 0.0, 0.0, 0.0, 0.0

    velocity_np = np.array(velocity_data)
    total_points_in_strokes = 0
    lsc, hsc, lsr, hsr = 0, 0, 0, 0

    all_s_list = []
    if strokes:
        all_s_list = (strokes.Compressions if strokes.Compressions else []) + \
                     (strokes.Rebounds if strokes.Rebounds else [])

    for s in all_s_list:
        if not (s and hasattr(s,'Stat') and s.Stat and hasattr(s.Stat, 'MaxVelocity') and s.Stat.MaxVelocity is not None and
                hasattr(s,'Start') and hasattr(s,'End') and
                s.Start <= s.End and s.Start >= 0 and s.End < len(velocity_np)):
            continue

        stroke_velocities = velocity_np[s.Start:s.End+1]
        if not stroke_velocities.size: continue

        num_points_in_current_stroke = len(stroke_velocities)
        total_points_in_strokes += num_points_in_current_stroke

        is_compression_stroke = s.Stat.MaxVelocity >= 0

        if is_compression_stroke:
            stroke_lsc_count = np.count_nonzero(stroke_velocities < high_speed_threshold)
            lsc += stroke_lsc_count
            hsc += num_points_in_current_stroke - stroke_lsc_count
        else:
            stroke_lsr_count = np.count_nonzero(stroke_velocities > -high_speed_threshold)
            lsr += stroke_lsr_count
            hsr += num_points_in_current_stroke - stroke_lsr_count

    if total_points_in_strokes == 0: return 0.0, 0.0, 0.0, 0.0
    hsr_perc = hsr / total_points_in_strokes * 100.0
    lsr_perc = lsr / total_points_in_strokes * 100.0
    lsc_perc = lsc / total_points_in_strokes * 100.0
    hsc_perc = hsc / total_points_in_strokes * 100.0
    return hsr_perc, lsr_perc, lsc_perc, hsc_perc


def velocity_band_stats_figure(strokes: Optional[Strokes], velocity_data: list[float],
                               high_speed_threshold: float) -> figure:
    hsr, lsr, lsc, hsc = _velocity_band_stats(strokes, velocity_data, high_speed_threshold)
    source_data = dict(x=[0], hsc=[hsc], lsc=[lsc], lsr=[lsr], hsr=[hsr])
    source = ColumnDataSource(name='ds_stats', data=source_data)

    total_perc = sum([val for val in [hsr, lsr, lsc, hsc] if val is not None and np.isfinite(val)])
    y_range_end_val = max(total_perc if total_perc > 0 and np.isfinite(total_perc) else 1.0, 1.0)

    p = figure(
        title="Speed\nzones",  # Split into two lines for limited space
        width=70, 
        height=600,
        x_range=(-0.5, 0.5), 
        y_range=(0, y_range_end_val),
        sizing_mode='fixed', 
        tools='', 
        toolbar_location=None)
    
    # Update title styling but keep center alignment for two-line title
    p.title.text_align = 'center'  # Changed from 'right' to 'center'
    p.title.align = 'center'
    p.title.text_font_size = '14px'
    
    p.grid.grid_line_color = None
    p.xaxis.visible = False; p.yaxis.visible = False

    stack_order = ['hsc', 'lsc', 'lsr', 'hsr']
    p.vbar_stack(stack_order, x='x', width=1, name='vbar_stack_bands',
                 color=['#303030', '#282828', '#282828', '#303030'],
                 line_color=['gray'] * 4, source=source)

    text_props = {'x': 0, 'x_units': 'data', 'y_units': 'data',
                  'text_baseline': 'middle', 'text_align': 'center',
                  'text_font_size': '13px',
                  'text_color': '#fefefe'}

    current_y_base = 0.0
    labels_info = []
    threshold = 0.1

    label_data = [
        ("HSC", hsc, 'l_hsc'), ("LSC", lsc, 'l_lsc'),
        ("LSR", lsr, 'l_lsr'), ("HSR", hsr, 'l_hsr')
    ]

    for text_prefix, val, name_attr in label_data:
        if val > threshold and np.isfinite(val):
            y_center = current_y_base + val / 2.0
            labels_info.append({'name': name_attr, 'y_center': y_center, 'text': f"{text_prefix}\n{val:.1f}%"})
        current_y_base += val if np.isfinite(val) else 0


    for info in labels_info:
        if info['y_center'] is not None and np.isfinite(info['y_center']):
            clamped_y = max(0, min(info['y_center'], y_range_end_val))
            p.add_layout(Label(name=info['name'], y=clamped_y, text=info['text'], **text_props))

    return p


def update_velocity_histogram(strokes: Optional[Strokes], velocity_data: list[float],
                              tbins: list[float], vbins: list[float],
                              vbins_fine: list[float],
                              high_speed_threshold: int) -> dict[str, Any]:
    step = vbins[1] - vbins[0] if vbins and len(vbins) > 1 else 1.0
    step_lowspeed = vbins_fine[1] - vbins_fine[0] if vbins_fine and len(vbins_fine) > 1 else 1.0

    data, data_lowspeed, mx, mx_lowspeed = _velocity_histogram_data(
        strokes, high_speed_threshold, tbins, vbins, vbins_fine)

    avgr, maxr, avgc, maxc, p95r, p95c = _velocity_stats(strokes, velocity_data)

    na_str = "N/A"
    maxr_txt = f"{maxr:.0f}" if maxr is not None and np.isfinite(maxr) else na_str
    p95r_txt = f"{p95r:.0f}" if p95r is not None and np.isfinite(p95r) else na_str
    avgr_txt = f"{avgr:.0f}" if avgr is not None and np.isfinite(avgr) else na_str
    avgc_txt = f"{avgc:.0f}" if avgc is not None and np.isfinite(avgc) else na_str
    p95c_txt = f"{p95c:.0f}" if p95c is not None and np.isfinite(p95c) else na_str
    maxc_txt = f"{maxc:.0f}" if maxc is not None and np.isfinite(maxc) else na_str

    col_width = 7

    textbox_content_update = (
        f"Max Reb:  {maxr_txt:>{col_width}} mm/s\n"
        f"P95 Reb:  {p95r_txt:>{col_width}} mm/s\n"
        f"Avg Reb:  {avgr_txt:>{col_width}} mm/s\n \n"
        f"Avg Comp: {avgc_txt:>{col_width}} mm/s\n"
        f"P95 Comp: {p95c_txt:>{col_width}} mm/s\n"
        f"Max Comp: {maxc_txt:>{col_width}} mm/s"
    )

    update_dict = dict(
        data=data, mx=max(1.0, mx if np.isfinite(mx) else 1.0),
        data_lowspeed=data_lowspeed, mx_lowspeed=max(1.0, mx_lowspeed if np.isfinite(mx_lowspeed) else 1.0),
        normal_data=_normal_distribution_data(strokes, velocity_data, step),
        normal_data_lowspeed=_normal_distribution_data(strokes, velocity_data, step_lowspeed),

        s_maxr_loc=maxr, s_p95r_loc=p95r, s_avgr_loc=avgr,
        s_maxc_loc=maxc, s_p95c_loc=p95c, s_avgc_loc=avgc,

        l_short_maxr_y=maxr, l_short_p95r_y=p95r, l_short_avgr_y=avgr,
        l_short_maxc_y=maxc, l_short_p95c_y=p95c, l_short_avgc_y=avgc,

        velocity_textbox_text=textbox_content_update
    )

    return update_dict


def update_velocity_band_stats(strokes: Optional[Strokes], velocity_data: list[float],
                               high_speed_threshold: float) -> dict[str, Any]:
    hsr, lsr, lsc, hsc = _velocity_band_stats(strokes, velocity_data, high_speed_threshold)

    y_positions = {}
    current_y_base = 0.0
    threshold = 0.01 # Kleiner Threshold, damit auch sehr kleine Anteile ein Label bekommen

    # Y-Positionen für JS auf Basis der tatsächlichen Stack-Reihenfolge
    # HSC ist unten im Stack
    if hsc > threshold : y_positions['y_hsc'] = current_y_base + hsc / 2.0
    current_y_base += hsc
    if lsc > threshold : y_positions['y_lsc'] = current_y_base + lsc / 2.0
    current_y_base += lsc
    if lsr > threshold : y_positions['y_lsr'] = current_y_base + lsr / 2.0
    current_y_base += lsr
    if hsr > threshold : y_positions['y_hsr'] = current_y_base + hsr / 2.0

    y_range_end_val = sum([val for val in [hsc, lsc, lsr, hsr] if val is not None and np.isfinite(val)])
    y_range_end_val = max(1.0, y_range_end_val if np.isfinite(y_range_end_val) else 1.0)

    # Sicherstellen, dass die y_positions innerhalb des gültigen Bereichs liegen
    for key in list(y_positions.keys()):
        if key in y_positions and y_positions[key] is not None and np.isfinite(y_positions[key]):
             y_positions[key] = max(0, min(y_positions[key], y_range_end_val))
        else:
            # Wenn eine Position nicht berechnet werden konnte (weil der Wert zu klein war),
            # setzen wir sie auf None, damit JS sie nicht verwendet oder einen Standardwert setzt.
            y_positions[key] = None # type: ignore


    return {
        "data": dict(x=[0], hsc=[hsc], lsc=[lsc], lsr=[lsr], hsr=[hsr]),
        "hsr_text": f"HSR\n{hsr:.1f}%" if hsr > threshold and np.isfinite(hsr) else "",
        "lsr_text": f"LSR\n{lsr:.1f}%" if lsr > threshold and np.isfinite(lsr) else "",
        "lsc_text": f"LSC\n{lsc:.1f}%" if lsc > threshold and np.isfinite(lsc) else "",
        "hsc_text": f"HSC\n{hsc:.1f}%" if hsc > threshold and np.isfinite(hsc) else "",
        **y_positions, # type: ignore
        "y_range_end": y_range_end_val
    }