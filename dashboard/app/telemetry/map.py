import io
import json
import math
import numpy as np
import gpxpy
import gpxpy.gpx
import xyzservices.providers as xyz

from typing import Any, Tuple, List, Dict, Union, Optional

from bokeh.models import Circle, ColumnDataSource, GlyphRenderer
from bokeh.models.callbacks import CustomJS
from bokeh.palettes import Spectral11
from bokeh.plotting import figure
from scipy.interpolate import pchip_interpolate


def _geographic_to_mercator(y_lat: float, x_lon: float) -> Union[Tuple[float, float], None]:
    if abs(x_lon) > 180 or abs(y_lat) >= 90:
        return None

    num = x_lon * 0.017453292519943295
    x_m = 6378137.0 * num
    a = y_lat * 0.017453292519943295
    y_m = 3189068.5 * math.log((1.0 + math.sin(a)) / (1.0 - math.sin(a)))
    return y_m, x_m


def _session_track(start: int, end: int, t: np.ndarray, track: Dict[str, List[float]]) -> Union[Dict[str, List[float]], None]:
    session_indices = np.where(np.logical_and(t >= start, t <= end))
    if len(session_indices[0]) == 0:
        return None

    start_idx = session_indices[0][0]
    end_idx = session_indices[0][-1] + 1

    session_lon = np.array(track['lon'][start_idx:end_idx])
    session_lat = np.array(track['lat'][start_idx:end_idx])
    session_time = np.array(t[start_idx:end_idx]) - start
    if len(session_time) > 0:
        session_time[0] = 0
    else:
        return None

    if len(session_time) < 2:
         if len(session_time) == 1:
             return dict(lon=list(session_lon), lat=list(session_lat))
         else:
             return dict(lon=[], lat=[])

    x_new_time = np.arange(0, session_time[-1], 0.1)
    if len(x_new_time) == 0 and len(session_time) > 0:
        x_new_time = np.array([0.0])

    if len(session_time) >= 2:
        yi = np.array([session_lon, session_lat])
        try:
            y_interpolated = pchip_interpolate(session_time, yi, x_new_time, axis=1)
            return dict(lon=list(y_interpolated[0, :]), lat=list(y_interpolated[1, :]))
        except ValueError:
            return dict(lon=list(session_lon), lat=list(session_lat))
    else:
        return dict(lon=list(session_lon), lat=list(session_lat))


def gpx_to_dict(gpx_data: bytes) -> Dict[str, List[float]]:
    gpx_dict: Dict[str, List[float]] = dict(lat=[], lon=[], ele=[], time=[])
    try:
        gpx_file = io.BytesIO(gpx_data)
        gpx = gpxpy.parse(gpx_file)
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    mercator_coords = _geographic_to_mercator(point.latitude, point.longitude)
                    if mercator_coords:
                        y_m, x_m = mercator_coords
                        gpx_dict['lat'].append(y_m)
                        gpx_dict['lon'].append(x_m)
                        gpx_dict['ele'].append(point.elevation if point.elevation is not None else 0.0)
                        if point.time:
                             gpx_dict['time'].append(point.time.timestamp())
                        else:
                             gpx_dict['time'].append(0.0)
    except Exception:
        return dict(lat=[], lon=[], ele=[], time=[])
    return gpx_dict


def track_data(track_json_str: Optional[str], start_timestamp: int, end_timestamp: int) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, List[float]]]]:
    if not track_json_str:
        return None, None

    try:
        full_track = json.loads(track_json_str)
    except json.JSONDecodeError:
        return None, None

    full_track_for_source = {k: v for k, v in full_track.items() if k in ['lon', 'lat']}
    timestamps = np.array(full_track.get('time', []))

    if not timestamps.any():
         return full_track_for_source, None

    session_track_data = _session_track(start_timestamp,
                                        end_timestamp,
                                        timestamps,
                                        full_track)

    return full_track_for_source, session_track_data


def map_figure() -> Tuple[figure, CustomJS]:
    ds_track = ColumnDataSource(name='ds_track', data=dict(lat=[], lon=[]))
    ds_session = ColumnDataSource(name='ds_session', data=dict(lat=[], lon=[]))

    source_start_point = ColumnDataSource(name='source_start_point', data=dict(x=[0], y=[0], size=[0]))
    source_end_point = ColumnDataSource(name='source_end_point', data=dict(x=[0], y=[0], size=[0]))
    source_pos_marker = ColumnDataSource(name='source_pos_marker', data=dict(x=[0], y=[0], size=[0]))

    p = figure(
        name='map',
        x_axis_type="mercator",
        y_axis_type="mercator",
        x_range=(-20037508.34, 20037508.34),
        y_range=(-20037508.34, 20037508.34),
        sizing_mode='stretch_both',
        min_height=300,
        match_aspect=True,
        tools='pan,wheel_zoom,reset',
        toolbar_location='above',
        active_drag='pan',
        active_scroll='wheel_zoom',
        output_backend='webgl')

    try:
        tile_provider = xyz.Jawg.Dark()
        if not hasattr(tile_provider, 'get_param'):
            raise AttributeError("Jawg provider not configured correctly")
        p.add_tile(tile_provider)
    except Exception:
        p.add_tile(xyz.OpenStreetMap.Mapnik)

    p.line(x='lon', y='lat', source=ds_track, name='track_line',
           color=Spectral11[3], alpha=0.5, width=2)
    p.line(x='lon', y='lat', source=ds_session, name='session_line',
           color=Spectral11[10], alpha=0.8, width=5)

    start_glyph_shape = Circle(x="x", y="y", radius="size", line_color='black', fill_color='#229954', fill_alpha=0.8)
    end_glyph_shape   = Circle(x="x", y="y", radius="size", line_color='black', fill_color='#E74C3C', fill_alpha=0.8)
    pos_marker_shape  = Circle(x="x", y="y", radius="size", line_color='black', fill_color='gray', fill_alpha=0.7)

    p.add_glyph(source_start_point, start_glyph_shape, name='start_point_renderer')
    p.add_glyph(source_end_point, end_glyph_shape, name='end_point_renderer')
    p.add_glyph(source_pos_marker, pos_marker_shape, name='pos_marker_renderer')

    on_resize = CustomJS(args=dict(dss=ds_session, map_fig=p), code='''
        const fig = map_fig;
        const ratio = fig.inner_height / fig.inner_width;
        let center_lon = 0;
        let center_lat = 0;
        let extent = 20037508.34; // Max Mercator extent

        if (dss.data && dss.data["lon"] && dss.data["lon"].length > 0) {
          center_lon = dss.data["lon"][0];
          center_lat = dss.data["lat"][0];
          extent = 600; // Zoom in
        }

        if (fig.x_range && fig.y_range) {
            fig.x_range.start = center_lon - (extent);
            fig.x_range.end = center_lon + (extent);
            fig.y_range.start = center_lat - (extent);
            fig.y_range.end = center_lat + (extent);
        }
        ''')
    p.js_on_change('inner_width', on_resize)
    p.js_on_change('inner_height', on_resize)

    on_seek = CustomJS(args=dict(dss=ds_session, pos_marker_source=source_pos_marker), code='''
        const location_seconds = cb_obj.location;
        if (isNaN(location_seconds) || !dss.data || !dss.data['lon'] || dss.data['lon'].length === 0) {
            pos_marker_source.data = {x: [], y: [], size: []};
            return;
        }

        const samples_per_second = 10;
        let idx = Math.floor(location_seconds * samples_per_second);

        idx = Math.max(0, Math.min(idx, dss.data['lon'].length - 1));

        const lon = dss.data['lon'][idx];
        const lat = dss.data['lat'][idx];

        if (lon !== undefined && lat !== undefined) {
            pos_marker_source.data = {x: [lon], y: [lat], size: [13]};
        } else {
            pos_marker_source.data = {x: [], y: [], size: []};
        }
        ''')

    return p, on_seek
