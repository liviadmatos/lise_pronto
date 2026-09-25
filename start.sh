#!/usr/bin/env bash
set -euo pipefail
python -m flask --app app:create_app check-db
exec gunicorn 'app:create_app()' --bind "0.0.0.0:${PORT:-8000}" --workers 2 --threads 2 --timeout 60
