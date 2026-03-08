#!/usr/bin/env bash
set -euo pipefail

# Regenerate cached Bokeh HTML for all sessions in the dashboard container.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "Error: docker-compose is not installed or not in PATH." >&2
  exit 1
fi

cd "${REPO_ROOT}"

sudo docker-compose exec -T dashboard python - <<'PY'
from dashboard import app
from app.extensions import db
from app.models.session import Session
from app.telemetry.session_html import create_cache

ok = 0
failed = 0
failed_ids = []

with app.app_context():
    sessions = db.session.execute(
        Session.select().order_by(Session.timestamp.asc())
    ).scalars().all()
    total = len(sessions)
    print(f"Found {total} sessions")

    for idx, s in enumerate(sessions, start=1):
        try:
            create_cache(s.id, 5, 200)
            ok += 1
            print(f"[{idx}/{total}] OK   {s.id}")
        except Exception as e:
            failed += 1
            failed_ids.append(str(s.id))
            print(f"[{idx}/{total}] FAIL {s.id} -> {e}")

print(f"Done. success={ok}, failed={failed}")
if failed_ids:
    print("Failed session IDs:")
    for sid in failed_ids:
        print(sid)
PY
