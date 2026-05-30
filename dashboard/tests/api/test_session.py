import base64
import hashlib
import uuid

import pytest

from flask import current_app
from http import HTTPStatus as status

from app.extensions import db
from app.models.session import Session
from conftest import DB_IDS, session_data, track_gpx


def test_get_all(client):
    response = client.get('/api/session')
    ids = [c['id'] for c in response.json]
    assert str(DB_IDS['session']) in ids


def test_get_incomplete(app, client):
    with app.app_context():
        session = Session.get(DB_IDS['session'])
        session.data = None
        db.session.commit()
    response = client.get('/api/session/incomplete')
    assert str(DB_IDS['session']) in response.json


def test_get_psst(client):
    id = str(DB_IDS['session'])
    response = client.get(f'/api/session/{id}/psst')
    session_data_hash = hashlib.sha256(session_data).digest().hex()
    assert hashlib.sha256(response.data).digest().hex() == session_data_hash


def test_get_psst_nonexistent(client):
    response = client.get(f'/api/session/{DB_IDS["nonexistent"]}/psst')
    assert response.status_code == status.NOT_FOUND


def test_get_last(client):
    id = str(DB_IDS['session_html'])
    response = client.get('/api/session/last')
    assert id == response.json['id']


def test_get_psst_invalid_uuid(client):
    with pytest.raises(ValueError) as e:
        client.get('/api/session/xxxx/psst')
    assert "badly formed" in str(e.value)


def test_get(client):
    id = str(DB_IDS['session'])
    response = client.get(f'/api/session/{id}')
    assert id == response.json['id']


def test_get_invalid_uuid(client):
    with pytest.raises(ValueError) as e:
        client.get('/api/session/xxxx')
    assert "badly formed" in str(e.value)


def test_get_nonexistent(client):
    response = client.get(f'/api/session/{DB_IDS["nonexistent"]}')
    assert response.status_code == status.NOT_FOUND


def test_filter(client):
    id = str(DB_IDS['session'])
    start = 10
    end = 13
    response = client.get(
        f'/api/session/{id}/filter?start={start}&end={end}')
    assert (hashlib.sha256(response.data).digest().hex() ==
            'e68e4aec59b75367578bd7045e43d2914f0b5152b7a09794ee4f87de08d16124')


@pytest.mark.parametrize(
    ('start', 'end'),
    (
        (-13, 13),
        (0, 1337),
        (13, 0),
    )
)
def test_filter_invalid_input(client, start, end):
    id = str(DB_IDS['session'])
    response = client.get(
        f'/api/session/{id}/filter?start={start}&end={end}')
    assert (hashlib.sha256(response.data).digest().hex() ==
            '83a1412a9a8c0f7b97b15121c6c33eedca0e89babe2312d65739d79c7c23d9c7')


def test_delete(client, auth):
    auth.login()

    client.delete(f'/api/session/{DB_IDS["session_html"]}')
    response = client.get(f'/api/session/{DB_IDS["session_html"]}')
    assert response.status_code == status.NOT_FOUND


def test_put(app, client, auth, requests_mock):
    auth.login()

    with app.app_context():
        api_server = current_app.config['GOSST_HTTP_API']
    url = f'{api_server}/api/internal/session'
    id = str(uuid.uuid4())
    requests_mock.put(url, json={'id': id}, status_code=status.CREATED)

    response = client.put('/api/session', json={"id": "dummy"})
    assert response.status_code == status.CREATED
    assert response.json['id'] == id


def test_put_invalid_data(app, client, auth, requests_mock):
    auth.login()

    with app.app_context():
        api_server = current_app.config['GOSST_HTTP_API']
    url = f'{api_server}/api/internal/session'
    id = str(uuid.uuid4())
    requests_mock.put(url, json={'id': id}, status_code=status.BAD_REQUEST)

    response = client.put('/api/session', json={"id": "dummy"})
    assert response.status_code == status.BAD_REQUEST


def test_put_normalized(app, client, auth, requests_mock):
    auth.login()

    with app.app_context():
        api_server = current_app.config['GOSST_HTTP_API']
    url = f'{api_server}/api/internal/session/normalized'
    id = str(uuid.uuid4())
    requests_mock.put(url, json={'id': id}, status_code=status.CREATED)

    response = client.put('/api/session/normalized', json={"id": "dummy"})
    assert response.status_code == status.CREATED
    assert response.json['id'] == id


def test_put_normalized_invalid_data(app, client, auth, requests_mock):
    auth.login()

    with app.app_context():
        api_server = current_app.config['GOSST_HTTP_API']
    url = f'{api_server}/api/internal/session'
    id = str(uuid.uuid4())
    requests_mock.put(url, json={'id': id}, status_code=status.BAD_REQUEST)

    response = client.put('/api/session', json={"id": "dummy"})
    assert response.status_code == status.BAD_REQUEST


def test_put_processed(client, auth):
    auth.login()

    id = str(uuid.uuid4())
    s_json = dict(
        id=id,
        name="test_session",
        description="session description",
        setup=DB_IDS['setup'],
        track=DB_IDS['track'],
        timestamp=1683457678,
        data=base64.b64encode(session_data).decode('utf-8'),
    )
    response = client.put('/api/session/psst', json=s_json)
    assert response.status_code == status.CREATED
    assert response.json['id'] == id


def test_put_processed_invalid_data(client, auth):
    auth.login()

    id = str(uuid.uuid4())
    s_json = dict(
        id=id,
        name="test_session",
        description="session description",
        setup=DB_IDS['setup'],
        track=DB_IDS['track'],
        timestamp=1683457678,
        data=base64.b64encode(b'test').decode('utf-8'),
    )
    response = client.put('/api/session/psst', json=s_json)
    assert response.status_code == status.BAD_REQUEST


def test_patch(auth, client):
    auth.login()

    patch_json = {'name': 'new_name', 'desc': 'new_description'}
    client.patch(f'/api/session/{DB_IDS["session"]}', json=patch_json)
    response = client.get(f'/api/session/{DB_IDS["session"]}')
    assert response.json['name'] == 'new_name'
    assert response.json['description'] == 'new_description'


def test_patch_psst(auth, client):
    auth.login()

    # get the original session
    response = client.get(f'/api/session/{DB_IDS["session"]}')
    session = response.json

    # check if patching really changes the 'data' field
    client.patch(f'/api/session/{DB_IDS["session"]}/psst', data='XXXX')
    response = client.get(f'/api/session/{DB_IDS["session"]}/psst')
    assert response.data == b'XXXX'

    # check if any other fields are unchanged
    response = client.get(f'/api/session/{DB_IDS["session"]}')
    new_session = response.json
    assert session == new_session


@pytest.mark.parametrize(
    ('id', 'message'),
    (
        (DB_IDS['session'], None),
        (DB_IDS['nonexistent'], b'does not exist'),
        (DB_IDS['session_html'], b'already generated'),
    )
)
def test_generate_bokeh(client, id, message):
    response = client.put(f'/api/session/{id}/bokeh')
    assert (response.status_code == status.NO_CONTENT or
            message in response.data)


@pytest.mark.parametrize(
    ('id', 'status'),
    (
        (DB_IDS['nonexistent'], status.NOT_FOUND),
        (DB_IDS['session'], status.NOT_FOUND),
        (DB_IDS['session_html'], status.OK),
    )
)
def test_session_html(client, auth, id, status):
    auth.login()

    response = client.get(f'/api/session/{id}/bokeh')
    assert response.status_code == status


def test_session_html_last(client, auth):
    auth.login()

    response = client.get('/api/session/last/bokeh')
    assert response.status_code == status.OK
    assert response.json['id'] == str(DB_IDS['session_html'])


def test_upload_gpx(client, auth):
    auth.login()

    id = DB_IDS['session_html']
    response = client.put(f'/api/session/{id}/gpx', data=track_gpx)
    assert response.status_code == status.OK
    assert hashlib.sha256(response.data).digest().hex() == (
        'acc6781678324e4b6dc52b8c7e76634f5d42276afb79612380d519f92aa26c04')


@pytest.mark.parametrize(
    ('id', 'status'),
    (
        (DB_IDS['nonexistent'], status.NOT_FOUND),
        (DB_IDS['session'], status.BAD_REQUEST),
    )
)
def test_upload_gpx_input_validation(client, auth, id, status):
    auth.login()

    response = client.put(f'/api/session/{id}/gpx', data=track_gpx)
    assert response.status_code == status


# --- Bokeh cache: new analysis columns (Phases 1-3) + discipline -----------

# divs index map for a dual-suspension session (order = `columns` in
# session_html.create_cache, minus session_id/script).
_DUAL_DIV_COLUMNS = [
    'travel', 'velocity', 'map', 'lr', 'sw',
    'f_thist', 'f_fft', 'f_vhist', 'r_thist', 'r_fft', 'r_vhist',
    'cbalance', 'rbalance', 'thist_comp', 'balance_metrics',
    'pv_front', 'pv_rear', 'pv_comp', 'accel_front', 'accel_rear', 'fr_scatter',
]


def test_create_cache_populates_new_columns(app):
    from app.models.session_html import SessionHtml
    from app.telemetry.session_html import create_cache

    with app.app_context():
        create_cache(DB_IDS['session'], 5, 200)
        sh = db.session.execute(
            db.select(SessionHtml).filter_by(session_id=DB_IDS['session'])
        ).scalar_one_or_none()
        assert sh is not None
        # All Phase 1-3 columns present for a dual-suspension session.
        for col in ('balance_metrics', 'pv_front', 'pv_rear', 'pv_comp',
                    'accel_front', 'accel_rear', 'fr_scatter'):
            assert getattr(sh, col), f"missing column {col}"
        # Div indices must stay stable (incremental append, no reorder).
        divs = list(sh.divs)
        assert len(divs) == len(_DUAL_DIV_COLUMNS)
        assert divs[13] and divs[14] and divs[15]  # comp / metrics / misc tabs


def test_create_cache_balance_metrics_table_content(app):
    from app.models.session_html import SessionHtml
    from app.telemetry.session_html import create_cache

    with app.app_context():
        create_cache(DB_IDS['session'], 5, 200)
        sh = db.session.execute(
            db.select(SessionHtml).filter_by(session_id=DB_IDS['session'])
        ).scalar_one_or_none()
        # The balance-metrics div is rendered into the document script (Bokeh
        # embeds Div text in the script payload, not the placeholder div).
        assert 'balance_metrics' in sh.balance_metrics or sh.balance_metrics
        assert 'Balance metrics' in sh.script
        assert 'Front SAG' in sh.script


def test_setup_discipline_defaults_to_enduro(app):
    from app.models.setup import Setup

    with app.app_context():
        setup = Setup.get(DB_IDS['setup'])
        # Column default applied on insert (conftest creates without discipline).
        assert setup.discipline == 'enduro'
