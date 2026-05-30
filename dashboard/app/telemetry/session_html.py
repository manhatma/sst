import msgpack
import numpy as np
import uuid

from bokeh.document import Document
from bokeh.events import DocumentReady
from bokeh.embed import components
from bokeh.layouts import column, row
from bokeh.models.callbacks import CustomJS
from bokeh.palettes import Spectral11
from bokeh.themes import built_in_themes, DARK_MINIMAL

from flask import current_app
from app.extensions import db
from app.models.session import Session
from app.models.session_html import SessionHtml
from app.models.setup import Setup
from app.telemetry.balance import balance_figure, velocity_balance_comparison_figure
from app.telemetry.balance_metrics import balance_metrics_figure
from app.telemetry.fft import fft_comparison_figure, fft_figure
from app.telemetry.leverage import leverage_ratio_figure, shock_wheel_figure
from app.telemetry.map import map_figure
from app.telemetry.misc_plots import (
    acceleration_figure,
    front_rear_scatter_figure,
    position_velocity_comparison_figure,
    position_velocity_figure,
)
from app.telemetry.psst import Telemetry, dataclass_from_dict
from app.telemetry.travel import travel_figure, travel_histogram_figure, travel_histogram_comparison_figure
from app.telemetry.velocity import velocity_figure
from app.telemetry.velocity import (
    velocity_histogram_figure,
    velocity_band_stats_figure
)


def _session_discipline(session) -> str:
    """Riding discipline from the session's setup; defaults to 'enduro'."""
    try:
        if session.setup:
            setup = Setup.get(session.setup)
            if setup and setup.discipline:
                return setup.discipline
    except Exception:
        current_app.logger.warning(
            "could not resolve discipline for session %s", session.id)
    return 'enduro'


def create_cache(session_id: uuid.UUID, lod: int, hst: int):
    front_color, rear_color = Spectral11[1], Spectral11[2]

    session = Session.get(session_id)
    if not session:
        return None

    discipline = _session_discipline(session)

    d = msgpack.unpackb(session.data)
    telemetry = dataclass_from_dict(Telemetry, d)

    tick = 1.0 / telemetry.SampleRate

    if telemetry.Front.Present:
        p_front_travel_hist = travel_histogram_figure(
            telemetry.Front,
            telemetry.Linkage.MaxFrontTravel,
            front_color,
            "Travel histogram (front)")
        p_front_vel_hist, p_front_vel_hist_ls = velocity_histogram_figure(
            telemetry.Front.Strokes,
            telemetry.Front.Velocity,
            telemetry.Front.TravelBins,
            telemetry.Front.VelocityBins,
            telemetry.Front.FineVelocityBins,
            hst,
            "Speed histogram (front)",
            "Low-speed (front)")
        p_front_vel_stats = velocity_band_stats_figure(
            telemetry.Front.Strokes,
            telemetry.Front.Velocity,
            hst)
        p_front_fft = fft_figure(
            telemetry.Front.Travel,
            telemetry.SampleRate,
            front_color,
            "Frequency (front)")

    if telemetry.Rear.Present:
        p_rear_travel_hist = travel_histogram_figure(
            telemetry.Rear,
            telemetry.Linkage.MaxRearTravel,
            rear_color,
            "Travel histogram (rear)")
        p_rear_vel_hist, p_rear_vel_hist_ls = velocity_histogram_figure(
            telemetry.Rear.Strokes,
            telemetry.Rear.Velocity,
            telemetry.Rear.TravelBins,
            telemetry.Rear.VelocityBins,
            telemetry.Rear.FineVelocityBins,
            hst,
            "Speed histogram (rear)",
            "Low-speed (rear)")
        p_rear_vel_stats = velocity_band_stats_figure(
            telemetry.Rear.Strokes,
            telemetry.Rear.Velocity,
            hst)
        p_rear_fft = fft_figure(
            telemetry.Rear.Travel,
            telemetry.SampleRate,
            rear_color,
            "Frequency (rear)")

    p_travel = travel_figure(telemetry, lod, front_color, rear_color)
    p_velocity = velocity_figure(telemetry, lod, front_color, rear_color)
    p_travel.x_range.js_link('start', p_velocity.x_range, 'start')
    p_travel.x_range.js_link('end', p_velocity.x_range, 'end')
    p_velocity.x_range.js_link('start', p_travel.x_range, 'start')
    p_velocity.x_range.js_link('end', p_travel.x_range, 'end')

    p_lr = leverage_ratio_figure(
        np.array(telemetry.Linkage.LeverageRatio), Spectral11[5])
    p_sw = shock_wheel_figure(telemetry.Linkage.ShockWheelCoeffs,
                              telemetry.Linkage.MaxRearStroke,
                              Spectral11[5])

    if telemetry.Front.Present and telemetry.Rear.Present:
        p_balance_compression = balance_figure(
            telemetry.Front.Strokes.Compressions,
            telemetry.Rear.Strokes.Compressions,
            telemetry.Linkage.MaxFrontTravel,
            telemetry.Linkage.MaxRearTravel,
            False,
            front_color,
            rear_color,
            'balance_compression',
            "Compression velocity balance")
        p_balance_rebound = balance_figure(
            telemetry.Front.Strokes.Rebounds,
            telemetry.Rear.Strokes.Rebounds,
            telemetry.Linkage.MaxFrontTravel,
            telemetry.Linkage.MaxRearTravel,
            True,
            front_color,
            rear_color,
            'balance_rebound',
            "Rebound velocity balance")

    on_seek_code = '''
        if (isNaN(cb_obj.location)) {
            return
        }
        if (dss.data['lat'].length != 0) {
            let idx = Math.floor(cb_obj.location * 10);
            if (idx < 0) {
                idx = 0;
            } else if (idx >= dss.data['lon'].length) {
                idx = dss.data['lon'].length - 1;
            }
            let lon = dss.data['lon'][idx];
            let lat = dss.data['lat'][idx];
            pos.x = lon;
            pos.y = lat;
        }
        SST.seekVideo(cb_obj.location)'''
    p_map, on_seek = map_figure()
    on_seek.code = on_seek_code
    p_travel.toolbar.active_inspect.overlay.js_on_change('location', on_seek)

    suspension_count = 0
    if telemetry.Front.Present:
        suspension_count += 1
    if telemetry.Rear.Present:
        suspension_count += 1

    dark_minimal_theme = built_in_themes[DARK_MINIMAL]
    document = Document()

    document.add_root(p_travel)
    document.add_root(p_velocity)
    document.add_root(p_map)
    document.add_root(p_lr)
    document.add_root(p_sw)
    columns = ['session_id', 'script', 'travel', 'velocity', 'map', 'lr', 'sw']

    if telemetry.Front.Present:
        prefix = 'front_' if suspension_count == 2 else ''
        p_front_travel_hist.name = f'{prefix}travel_hist'
        p_front_fft.name = f'{prefix}fft'
        p_front_velocity = row(
            name=f'{prefix}velocity_hist',
            sizing_mode='stretch_width',
            children=[
                p_front_vel_hist,
                p_front_vel_hist_ls,
                p_front_vel_stats])
        document.add_root(p_front_travel_hist)
        document.add_root(p_front_fft)
        document.add_root(p_front_velocity)
        columns.extend(['f_thist', 'f_fft', 'f_vhist'])
    if telemetry.Rear.Present:
        prefix = 'rear_' if suspension_count == 2 else ''
        p_rear_travel_hist.name = f'{prefix}travel_hist'
        p_rear_fft.name = f'{prefix}fft'
        p_rear_velocity = row(
            name=f'{prefix}velocity_hist',
            sizing_mode='stretch_width',
            children=[
                p_rear_vel_hist,
                p_rear_vel_hist_ls,
                p_rear_vel_stats])
        document.add_root(p_rear_travel_hist)
        document.add_root(p_rear_fft)
        document.add_root(p_rear_velocity)
        columns.extend(['r_thist', 'r_fft', 'r_vhist'])
    if suspension_count == 2:
        document.add_root(p_balance_compression)
        document.add_root(p_balance_rebound)
        columns.extend(['cbalance', 'rbalance'])

        p_thist_comp_fig = travel_histogram_comparison_figure(
            telemetry.Front,
            telemetry.Rear,
            telemetry.Linkage.MaxFrontTravel,
            telemetry.Linkage.MaxRearTravel,
            front_color,
            rear_color,
        )
        p_fft_comp = fft_comparison_figure(
            telemetry.Front.Travel,
            telemetry.Rear.Travel,
            telemetry.SampleRate,
            front_color,
            rear_color,
        )
        p_vel_balance_comp = velocity_balance_comparison_figure(
            telemetry.Front.Strokes,
            telemetry.Rear.Strokes,
            telemetry.Linkage.MaxFrontTravel,
            telemetry.Linkage.MaxRearTravel,
            front_color,
            rear_color,
        )
        p_thist_comp_fig.sizing_mode = 'stretch_both'
        p_thist_comp_fig.min_height = 260
        p_fft_comp.sizing_mode = 'stretch_both'
        p_fft_comp.min_height = 220
        p_vel_balance_comp.sizing_mode = 'stretch_both'

        # Keep x-axis labels visible by deriving bottom padding from current plot height.
        dynamic_bottom_padding_code = '''
            const innerH = cb_obj.inner_height;
            const outerH = cb_obj.height;
            const h = Number.isFinite(innerH) && innerH > 0 ? innerH : outerH;
            if (!Number.isFinite(h) || h <= 0) {
                return;
            }
            const dynamicPadding = Math.max(18, Math.round(h * 0.12));
            if (cb_obj.min_border_bottom !== dynamicPadding) {
                cb_obj.min_border_bottom = dynamicPadding;
            }
        '''
        p_fft_comp.js_on_change('inner_height', CustomJS(code=dynamic_bottom_padding_code))
        p_fft_comp.js_on_change('height', CustomJS(code=dynamic_bottom_padding_code))
        p_vel_balance_comp.js_on_change('inner_height', CustomJS(code=dynamic_bottom_padding_code))
        p_vel_balance_comp.js_on_change('height', CustomJS(code=dynamic_bottom_padding_code))

        p_left_col = column(
            sizing_mode='stretch_both',
            children=[p_thist_comp_fig, p_fft_comp])
        p_thist_comp = row(
            name='thist_comp',
            sizing_mode='stretch_both',
            children=[p_left_col, p_vel_balance_comp])
        document.add_root(p_thist_comp)
        columns.append('thist_comp')

        # Phase 2: discipline-aware balance-metrics table (dual suspension only).
        p_balance_metrics = balance_metrics_figure(telemetry, discipline)
        document.add_root(p_balance_metrics)
        columns.append('balance_metrics')

        # Phase 3: Misc tab — phase portraits, acceleration, front/rear scatter.
        p_pv_front = position_velocity_figure(telemetry, 'front', front_color)
        p_pv_rear = position_velocity_figure(telemetry, 'rear', rear_color)
        p_pv_comp = position_velocity_comparison_figure(
            telemetry, front_color, rear_color)
        p_accel_front = acceleration_figure(
            telemetry.Front, telemetry.SampleRate, front_color,
            "Front acceleration over time", "Front")
        p_accel_rear = acceleration_figure(
            telemetry.Rear, telemetry.SampleRate, rear_color,
            "Rear acceleration over time", "Rear")
        p_fr_scatter = front_rear_scatter_figure(telemetry, rear_color)
        document.add_root(p_pv_front)
        document.add_root(p_pv_rear)
        document.add_root(p_pv_comp)
        document.add_root(p_accel_front)
        document.add_root(p_accel_rear)
        document.add_root(p_fr_scatter)
        columns.extend(['pv_front', 'pv_rear', 'pv_comp',
                        'accel_front', 'accel_rear', 'fr_scatter'])

    document.js_on_event(DocumentReady, CustomJS(
        args=dict(), code='SST.init_models();'))

    script, divs = components(document.roots, theme=dark_minimal_theme)
    components_data = dict(zip(columns, [session_id, script] + list(divs)))
    session_html_object = dataclass_from_dict(SessionHtml, components_data)

    existing_html_entry = SessionHtml.query.filter_by(session_id=session_id).first()
    if existing_html_entry:
        db.session.delete(existing_html_entry)
        if current_app.debug:
            db.session.commit()

    db.session.add(session_html_object)
    db.session.commit()
