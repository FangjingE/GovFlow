#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[govflow] starting db + adminer..."
docker compose up -d db adminer

if [[ -x "./.venv/bin/python" ]]; then
  echo "[govflow] starting api with .venv python..."
  exec ./.venv/bin/python -m uvicorn govflow.main:app --reload --app-dir src "$@"
fi

echo "[govflow] .venv not found, using current python..."
exec python -m uvicorn govflow.main:app --reload --app-dir src "$@"
