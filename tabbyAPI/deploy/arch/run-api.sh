#!/usr/bin/env bash
# Start watch_api.py with access to the docker socket when this Linux account
# is in the docker group, including before a re-login.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/venv/bin/python"
if [[ -w /var/run/docker.sock ]]; then
  exec "$PY" watch_api.py
fi
if command -v sg >/dev/null 2>&1 && sg docker -c true >/dev/null 2>&1; then
  exec sg docker -c "exec \"$PY\" watch_api.py"
fi
if command -v sudo >/dev/null 2>&1 && sudo -n -u "$USER" -g docker true >/dev/null 2>&1; then
  exec sudo -n -u "$USER" -g docker "$PY" watch_api.py
fi
exec "$PY" watch_api.py
