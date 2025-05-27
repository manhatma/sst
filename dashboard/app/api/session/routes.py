import json
import msgpack
import requests
import uuid

from bokeh import __version__ as bokeh_version
from io import BytesIO
from http import HTTPStatus as status
from datetime import datetime
from typing import Tuple

from flask import current_app, jsonify, request, send_file
from flask_jwt_extended import (
    jwt_required,
    verify_jwt_in_request,
    unset_jwt_cookies
)
from markupsafe import Markup

from app import id_queue
from app.api.common import get_entity, delete_entity
from app.api.session import bp
from app.extensions import db
from app.models.session import Session
from app.models.session_html import SessionHtml
from app.models.track import Track

from app.telemetry.balance import update_balance
from app.telemetry.fft import update_fft
from app.telemetry.map import gpx_to_dict, track_data
from app.telemetry.psst import Suspension, Strokes, Telemetry, dataclass_from_dict
from app.telemetry.session_html import create_cache
from app.telemetry.travel import update_travel_histogram
from app.telemetry.velocity import (
    update_velocity_band_stats,
    update_velocity_histogram
)

def _filter_strokes(strokes, start, end):
    if start is None or end is None:
        return strokes

    filtered_compressions = []
    if strokes.Compressions:
        for c in strokes.Compressions:
            if hasattr(c, 'Start') and c.Start is not None and \
               hasattr(c, 'End') and c.End is not None and \
               c.Start > start and c.End < end:
                filtered_compressions.append(c)

    filtered_rebounds = []
    if strokes.Rebounds:
        for r in strokes.Rebounds:
            if hasattr(r, 'Start') and r.Start is not None and \
               hasattr(r, 'End') and r.End is not None and \
               r.Start > start and r.End < end:
                filtered_rebounds.append(r)
                
    return Strokes(Compressions=filtered_compressions, Rebounds=filtered_rebounds)

def _extract_range(sample_rate: int) -> Tuple[int, int]:
    try:
        start_str = request.args.get('start')
        start = int(float(start_str) * sample_rate) if start_str is not None else None
    except Exception:
        start = None
    try:
        end_str = request.args.get('end')
        end = int(float(end_str) * sample_rate) if end_str is not None else None
    except Exception:
        end = None
    return start, end

def _validate_range(start: int, end: int, count: int) -> bool:
    return (start is not None and end is not None and start >= 0 and end < count and start < end)

def _update_stroke_based(strokes: Strokes, suspension: Suspension, telemetry_linkage_max_travel: float, travel_data: list[float], selection_start_abs_index: int):
    thist = update_travel_histogram(
        strokes,
        travel_data,
        suspension.TravelBins,
        telemetry_linkage_max_travel,
        selection_start_abs_index
    )
    vhist = update_velocity_histogram(
        strokes,
        suspension.Velocity,
        suspension.TravelBins,
        suspension.VelocityBins,
        suspension.FineVelocityBins,
        200
    )
    vbands = update_velocity_band_stats(
        strokes,
        suspension.Velocity,
        200
    )
    return dict(
        thist=thist,
        vhist=vhist,
        vbands=vbands,
        balance=None
    )

@bp.route('', methods=['GET'])
def get_all():
    entities = db.session.execute(
        Session.select().order_by(Session.timestamp.desc())
    ).scalars()
    return jsonify(list(entities)), status.OK

@bp.route('/incomplete', methods=['GET'])
def get_incomplete():
    query = db.select(Session.id).filter_by(deleted=None, data=None)
    entities = db.session.execute(query).scalars()
    return jsonify(list(entities)), status.OK

@bp.route('/<uuid:id>/psst', methods=['GET'])
def get_psst(id: uuid.UUID):
    entity = Session.get(id)
    if not entity:
        return jsonify(msg="Session does not exist!"), status.NOT_FOUND
    data = BytesIO(entity.data)
    return send_file(
        data,
        as_attachment=True,
        download_name=f"{entity.name}.psst",
        mimetype="application/octet-stream",
    )

@bp.route('/last', methods=['GET'])
def get_last():
    entity = db.session.execute(
        Session.select().order_by(Session.timestamp.desc()).limit(1)
    ).scalar_one_or_none()
    if not entity:
        return jsonify(msg="Session does not exist!"), status.NOT_FOUND
    return jsonify(entity), status.OK

@bp.route('/<uuid:id>', methods=['GET'])
def get(id: uuid.UUID):
    return get_entity(Session, id)

@bp.route('/<uuid:id>/filter', methods=['GET'])
def filter(id: uuid.UUID):
    entity = Session.get(id)
    if not entity:
        return jsonify(msg="Session does not exist!"), status.NOT_FOUND

    d = msgpack.unpackb(entity.data)
    t = dataclass_from_dict(Telemetry, d)

    start, end = _extract_range(t.SampleRate)
    count = len(t.Front.Travel if t.Front.Present else t.Rear.Travel)
    if not _validate_range(start, end, count):
        start, end = None, None

    updated_data = {'front': None, 'rear': None}
    tick = 1.0 / t.SampleRate

    actual_selection_start_index_front = 0
    actual_selection_start_index_rear = 0

    if t.Front.Present:
        if start is not None and end is not None:
            f_strokes = _filter_strokes(t.Front.Strokes, start, end)
            travel_data_for_hist_and_fft = t.Front.Travel[start:end]
            actual_selection_start_index_front = start
        else:
            f_strokes = t.Front.Strokes
            travel_data_for_hist_and_fft = t.Front.Travel
        
        updated_data['front'] = _update_stroke_based(
            f_strokes,
            t.Front,
            t.Linkage.MaxFrontTravel,
            travel_data_for_hist_and_fft,
            actual_selection_start_index_front
        )
        updated_data['front']['fft'] = update_fft(travel_data_for_hist_and_fft, tick)

    if t.Rear.Present:
        if start is not None and end is not None:
            r_strokes = _filter_strokes(t.Rear.Strokes, start, end)
            travel_data_for_hist_and_fft_rear = t.Rear.Travel[start:end]
            actual_selection_start_index_rear = start
        else:
            r_strokes = t.Rear.Strokes
            travel_data_for_hist_and_fft_rear = t.Rear.Travel

        updated_data['rear'] = _update_stroke_based(
            r_strokes,
            t.Rear,
            t.Linkage.MaxRearTravel,
            travel_data_for_hist_and_fft_rear,
            actual_selection_start_index_rear
        )
        updated_data['rear']['fft'] = update_fft(travel_data_for_hist_and_fft_rear, tick)

    if t.Front.Present and t.Rear.Present:
        f_balance_strokes = _filter_strokes(t.Front.Strokes, start, end)
        r_balance_strokes = _filter_strokes(t.Rear.Strokes, start, end)
        updated_data['balance'] = dict(
            compression=update_balance(
                f_balance_strokes.Compressions,
                r_balance_strokes.Compressions,
                t.Linkage.MaxFrontTravel,
                t.Linkage.MaxRearTravel
            ),
            rebound=update_balance(
                f_balance_strokes.Rebounds,
                r_balance_strokes.Rebounds,
                t.Linkage.MaxFrontTravel,
                t.Linkage.MaxRearTravel
            ),
        )

    return jsonify(updated_data)

@bp.route('/<uuid:id>', methods=['DELETE'])
@jwt_required()
def delete(id: uuid.UUID):
    delete_entity(Session, id)
    db.session.execute(db.delete(SessionHtml).filter_by(session_id=id))
    db.session.commit()
    return '', status.NO_CONTENT

@bp.route('', methods=['PUT'])
@jwt_required()
def put():
    api_server = current_app.config['GOSST_HTTP_API']
    url = f'{api_server}/api/internal/session'
    resp = requests.put(url, json=request.json)
    if resp.status_code == status.CREATED:
        return jsonify(id=resp.json()['id']), status.CREATED
    else:
        return jsonify(msg="Session could not be imported"), status.BAD_REQUEST

@bp.route('/normalized', methods=['PUT'])
@jwt_required()
def put_normalized():
    api_server = current_app.config['GOSST_HTTP_API']
    url = f'{api_server}/api/internal/session/normalized'
    resp = requests.put(url, json=request.json)
    if resp.status_code == status.CREATED:
        return jsonify(id=resp.json()['id']), status.CREATED
    else:
        return jsonify(msg="Session could not be imported"), status.BAD_REQUEST

@bp.route('/psst', methods=['PUT'])
@jwt_required()
def put_processed():
    session_dict = request.json
    session_data = session_dict.pop('data')
    entity = dataclass_from_dict(Session, session_dict)
    if not entity:
        return jsonify(msg="Invalid data for Session"), status.BAD_REQUEST
    try:
        entity.psst = session_data
    except Exception:
        return jsonify(msg="Invalid data for Session"), status.BAD_REQUEST
    entity = db.session.merge(entity)
    db.session.commit()
    generate_bokeh(entity.id)
    return jsonify(id=entity.id), status.CREATED

@bp.route('/<uuid:id>', methods=['PATCH'])
@jwt_required()
def patch(id: uuid.UUID):
    data = request.json
    db.session.execute(db.update(Session).filter_by(id=id).values(
        name=data.get('name'),
        description=data.get('desc'),
        front_springrate=data.get('front_springrate'),
        rear_springrate=data.get('rear_springrate'),
        front_hsc=data.get('front_hsc'),
        rear_hsc=data.get('rear_hsc'),
        front_lsc=data.get('front_lsc'),
        rear_lsc=data.get('rear_lsc'),
        front_lsr=data.get('front_lsr'),
        rear_lsr=data.get('rear_lsr'),
        front_hsr=data.get('front_hsr'),
        rear_hsr=data.get('rear_hsr'),
    ))
    db.session.commit()
    return '', status.NO_CONTENT

@bp.route('/<uuid:id>/psst', methods=['PATCH'])
@jwt_required()
def patch_psst(id: uuid.UUID):
    session = Session.get(id)
    if not session:
        return jsonify(), status.NOT_FOUND
    db.session.execute(db.update(Session).filter_by(id=id).values(
        data=request.data,
        updated=session.updated,
    ))
    db.session.commit()
    generate_bokeh(id)
    return '', status.NO_CONTENT

@bp.route('/<uuid:id>/bokeh', methods=['PUT'])
def generate_bokeh(id: uuid.UUID):
    s = Session.get(id)
    if not s:
        return jsonify(msg=f"session #{id} does not exist"), status.BAD_REQUEST

    sh = db.session.execute(
        db.select(SessionHtml).filter_by(session_id=id)
    ).scalar_one_or_none()

    if not sh or current_app.debug:
        id_queue.put(id)
        return '', status.ACCEPTED

    return jsonify(msg=f"already generated (session {id})"), status.OK

@bp.route('/last/bokeh', methods=['GET'], defaults={'session_id': None})
@bp.route('/<uuid:session_id>/bokeh', methods=['GET'])
def session_html(session_id: uuid.UUID):
    try:
        verify_jwt_in_request()
        full_access = True
    except Exception:
        full_access = False

    if not session_id:
        session = db.session.execute(
            Session.select().order_by(Session.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
    else:
        session = Session.get(session_id)
    if not session:
        return jsonify(), status.NOT_FOUND

    session_html_entry = db.session.execute(
        db.select(SessionHtml).filter_by(session_id=session.id)
    ).scalar_one_or_none()
    if not session_html_entry:
        return jsonify(msg=f"Bokeh HTML for session {session.id} not yet generated."), status.NOT_FOUND

    components_script = Markup(
        session_html_entry.script
            .replace('<script type="text/javascript">', '')
            .replace('</script>', '')
    )
    components_divs = [Markup(d) for d in session_html_entry.divs]

    track = Track.get(session.track)
    d = msgpack.unpackb(session.data)
    t = dataclass_from_dict(Telemetry, d)

    suspension_count = int(t.Front.Present) + int(t.Rear.Present)
    record_num = len(t.Front.Travel) if t.Front.Present else len(t.Rear.Travel)
    elapsed_time = record_num / t.SampleRate
    start_time = session.timestamp
    end_time = start_time + elapsed_time

    full_track, session_track = track_data(
        track.track if track else None,
        start_time, end_time
    )

    response = jsonify(
        id=session.id,
        name=session.name,
        description=session.description,
        front_springrate=session.front_springrate,
        rear_springrate=session.rear_springrate,
        front_hsc=session.front_hsc,
        rear_hsc=session.rear_hsc,
        front_lsc=session.front_lsc,
        rear_lsc=session.rear_lsc,
        front_lsr=session.front_lsr,
        rear_lsr=session.rear_lsr,
        front_hsr=session.front_hsr,
        rear_hsr=session.rear_hsr,
        start_time=start_time,
        end_time=end_time,
        suspension_count=suspension_count,
        full_track=full_track,
        session_track=session_track,
        script=components_script,
        divs=components_divs,
        full_access=full_access,
    )
    if not full_access:
        unset_jwt_cookies(response)
    return response