from bokeh.resources import CDN
from pathlib import Path
from flask import render_template
from markupsafe import Markup

from app.frontend import bp


@bp.route('/')
def dashboard():
    main_js_path = Path(__file__).resolve().parent.parent / 'static' / 'main.js'
    main_js_version = int(main_js_path.stat().st_mtime) if main_js_path.exists() else 0
    return render_template(
        'index.html',
        resources=Markup(CDN.render()),
        main_js_version=main_js_version,
    )
