#!/usr/bin/env bash
# Run Disha locally on http://localhost:8080 (a secure context, so the mic works).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet -r requirements-dev.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example: set GOOGLE_CLOUD_PROJECT (or GEMINI_API_KEY), then re-run." >&2
  exit 1
fi

exec .venv/bin/uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port "${PORT:-8080}" --env-file .env
