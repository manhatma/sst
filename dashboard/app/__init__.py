import logging
import queue
import threading
import sys

import click

from http import HTTPStatus as status
from datetime import datetime, timedelta, timezone

from flask import jsonify, Flask, current_app
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    set_access_cookies,
    get_current_user
)
from werkzeug.exceptions import HTTPException

from app.extensions import db, jwt, migrate, sio
from app.telemetry.session_html import create_cache
from app.utils.first_init import first_init
from app.utils.converters import UuidConverter

id_queue = queue.Queue()

def _sqlite_pragmas(app: Flask):
    if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
        def _pragma_on_connect(dbapi_con, con_record):
            dbapi_con.execute('PRAGMA journal_mode=WAL')

        with app.app_context():
            from sqlalchemy import event
            event.listen(db.engine, 'connect', _pragma_on_connect)

def create_app(test_config=None):
    app = Flask(__name__)

    app.config['JWT_TOKEN_LOCATION'] = ['cookies', 'headers']
    app.config['JWT_ALGORITHM'] = 'RS256'
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
    app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)
    app.config['JWT_COOKIE_SECURE'] = True

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/gosst.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.config['GOSST_HTTP_API'] = 'http://localhost:8080'

    if test_config:
        app.config.update(test_config)
    else:
        app.config.from_prefixed_env()

    app.logger.addHandler(logging.StreamHandler(sys.stdout))
    app.logger.setLevel(logging.DEBUG)
   
    app.url_map.converters['uuid'] = UuidConverter

    ctx = click.get_current_context(silent=True)
    if not ctx:
        private_key_file = app.config.get('JWT_PRIVATE_KEY_FILE', './jwt_keys/private_key.pem')
        public_key_file = app.config.get('JWT_PUBLIC_KEY_FILE', './jwt_keys/public_key.pem')
        try:
            app.config['JWT_PRIVATE_KEY'] = open(private_key_file).read()
            app.config['JWT_PUBLIC_KEY'] = open(public_key_file).read()
        except FileNotFoundError:
            app.logger.error(f"JWT Key files not found: {private_key_file}, {public_key_file}. "
                             "Ensure they are mounted into the container or paths are correctly configured via environment variables.")

    @app.cli.command("init")
    def init_command():
        first_init()

    @app.after_request
    def refresh_expiring_jwts(response):
        try:
            exp_timestamp = get_jwt()["exp"]
            now = datetime.now(timezone.utc)
            target_timestamp = datetime.timestamp(now + timedelta(minutes=10))
            if target_timestamp > exp_timestamp:
                access_token = create_access_token(identity=get_current_user())
                set_access_cookies(response, access_token)
            return response
        except (RuntimeError, KeyError):
            return response

    @app.errorhandler(HTTPException)
    def handle_exception(e):
        return jsonify(status=e.code, msg=e.name), e.code

    jwt.init_app(app)
    sio.init_app(app)
    db.init_app(app)
    _sqlite_pragmas(app)
    migrate.init_app(app, db)

    from app.frontend import bp as frontend_bp
    app.register_blueprint(frontend_bp)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    def html_generator():
        with app.app_context():
            while True:
                try:
                    id_from_queue = id_queue.get()
                    create_cache(id_from_queue, 5, 200)
                    sio.emit("session_ready")
                except Exception as e:
                    session_id_for_log = id_from_queue if 'id_from_queue' in locals() and id_from_queue is not None else 'unknown_id'
                    app.logger.error(f"Cache generation failed for session {session_id_for_log}: {e}", exc_info=True)

    if not app.config.get('TESTING', False) and not app.config.get('DISABLE_HTML_GENERATOR', False):
        generator_thread = threading.Thread(target=html_generator)
        generator_thread.daemon = True
        generator_thread.start()
    return app
