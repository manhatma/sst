import io
import json
import math
import numpy as np
import gpxpy
import gpxpy.gpx
import xyzservices.providers as xyz

from typing import Any

from bokeh.models import Circle, ColumnDataSource
from bokeh.models.callbacks import CustomJS
from bokeh.palettes import Spectral11
from bokeh.plotting import figure
from scipy.interpolate import pchip_interpolate


def _geographic_to_mercator(y_lat: float, x_lon: float) -> (float, float):
    if abs(x_lon) > 180 or abs(y_lat) >= 90:
        return None

    num = x_lon * 0.017453292519943295
    x_m = 6378137.0 * num
    a = y_lat * 0.017453292519943295
    y_m = 3189068.5 * math.log((1.0 + math.sin(a)) / (1.0 - math.sin(a)))
    return y_m, x_m


def _session_track(start: int, end: int, t: np.array, track: dict) -> (
                   dict[str, list[float]]):
    session_indices = np.where(np.logical_and(t >= start, t <= end))
    if len(session_indices[0]) == 0:
        return None

    start_idx = session_indices[0][0]
    end_idx = session_indices[0][-1] + 1  # +1, so that the last is included

    session_lon = np.array(track['lon'][start_idx:end_idx])
    session_lat = np.array(track['lat'][start_idx:end_idx])
    session_time = np.array(t[start_idx:end_idx]) - start
    session_time[0] = 0

    x = np.arange(0, session_time[-1], 0.1)
    yi = np.array([session_lon, session_lat])
    y = pchip_interpolate(session_time, yi, x, axis=1)

    return dict(lon=list(y[0, :]), lat=list(y[1, :]))


def gpx_to_dict(gpx_data: str) -> dict[str, Any]:
    gpx_dict = dict(lat=[], lon=[], ele=[], time=[])
    gpx_file = io.BytesIO(gpx_data)
    gpx = gpxpy.parse(gpx_file)
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                lat, lon = _geographic_to_mercator(point.latitude,
                                                   point.longitude)
                gpx_dict['lat'].append(lat)
                gpx_dict['lon'].append(lon)
                gpx_dict['ele'].append(point.elevation)
                gpx_dict['time'].append(point.time.timestamp())
    return gpx_dict


def track_data(track: str, start_timestamp: int, end_timestamp: int) -> (
               dict[str, Any], dict[str, list[float]]):
    if not track:
        return None, None

    if type(track) is str:
        full_track = json.loads(track)
    else:
        full_track = dict(track)  # Copy, so that we leage the original intact.

    # We don't yet use elevation data, so currently there is no need to include
    # it in the datasource. It is just saved to the database for future use.
    full_track.pop('ele', None)
    # We also do not need to include time data in the datasource, but we need
    # it for later calculations.
    timestamps = np.array(full_track.pop('time', None))

    session_track = _session_track(start_timestamp,
                                   end_timestamp,
                                   timestamps,
                                   full_track)

    return full_track, session_track


def map_figure() -> (figure, CustomJS):
    ds_track = ColumnDataSource(name='ds_track', data=dict(lat=[], lon=[]))
    ds_session = ColumnDataSource(name='ds_session', data=dict(lat=[], lon=[]))

    p = figure(
        name='map',
        x_axis_type=None,
        y_axis_type=None,
        x_range=(-20037508.340, 20037508.34),
        y_range=(-20037508.34, 20037508.34),
        sizing_mode='stretch_both',
        min_height=300,
        match_aspect=True,
        tools='pan,wheel_zoom',
        toolbar_location='above',
        active_drag='pan',
        active_scroll='wheel_zoom',
        output_backend='webgl')
    tile_provider = xyz.Jawg.Dark(
        accessToken='lK4rYCmlPZb5Fj4GjObrgGYo0IQnEz00hWXR7lpmRUHQ2a9R6jwr8aEpaSJxh5tn',
        variant='aa40616c-c117-442e-ae6f-901ffa0e14a4'
    )
    p.add_tile(tile_provider)
    p.line(x='lon', y='lat', source=ds_track,
           color=Spectral11[3], alpha=0.5, width=2)
    p.line(x='lon', y='lat', source=ds_session,
           color=Spectral11[10], alpha=0.8, width=5)
    cs = Circle(name='start_point', x=0, y=0, radius=10,
                line_color='black', fill_color='#229954', fill_alpha=0.8)
    ce = Circle(name='end_point', x=0, y=0, radius=10,
                line_color='black', fill_color='#E74C3C', fill_alpha=0.8)
    p.add_glyph(cs)
    p.add_glyph(ce)

    pos_marker = Circle(name="pos_marker", x=0, y=0, radius=13,
                        line_color='black', fill_color='gray')
    p.add_glyph(pos_marker)

    on_resize = CustomJS(args=dict(dss=ds_session), code='''
        const ratio = cb_obj.inner_width / cb_obj.inner_height;
        var start_lon = 0
        var start_lat = 0
        var range = 20037508.34
        if (dss.data["lon"].length != 0) {
          start_lon = dss.data["lon"][0]
          start_lat = dss.data["lat"][0]
          range = 600
        }
        cb_obj.x_range.start = start_lon - (range * ratio);
        cb_obj.x_range.end = start_lon + (range * ratio);
        cb_obj.y_range.start = start_lat - range;
        cb_obj.y_range.end = start_lat + range;
        ''')
    p.js_on_change('inner_width', on_resize)
    p.js_on_change('inner_height', on_resize)

    on_seek = CustomJS(args=dict(dss=ds_session, pos=pos_marker), code='')

    return p, on_seek
