#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$project_root/.venv/bin/uvicorn" src.backend.app:app --app-dir "$project_root" --host 127.0.0.1 --port 8765
