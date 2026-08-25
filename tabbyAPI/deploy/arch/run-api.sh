#!/usr/bin/env bash
# Start watch_api.py with access to the docker socket when this Linux account
# is in the docker group, including before a re-login.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/venv/bin/python"
ENV_FILE="$ROOT/deploy/arch/tabby.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
# sudo env_reset drops systemd EnvironmentFile / sourced tabby.env. Re-inject
# stack settings so the reverse SSH tunnel and public URL still work.
exec_docker_group() {
  local args=() name
  local names
  names="$( { compgen -e TABBY_ || true; compgen -e COMFYUI_ || true; } )"
  for name in $names; do
    args+=("$name=${!name}")
  done
  exec sudo -n -u "$USER" -g docker /usr/bin/env "${args[@]}" "$@"
}
# Code-mode Term talks to docker. Wait briefly if the daemon is still coming up.
if command -v docker >/dev/null 2>&1 && [[ ! -S /var/run/docker.sock ]]; then
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [[ -S /var/run/docker.sock ]] && break
    sleep 1
  done
fi
if [[ -w /var/run/docker.sock ]]; then
  exec "$PY" watch_api.py
fi
if command -v sg >/dev/null 2>&1 && sg docker -c true >/dev/null 2>&1; then
  exec sg docker -c "exec \"$PY\" watch_api.py"
fi
if command -v sudo >/dev/null 2>&1 && sudo -n -u "$USER" -g docker true >/dev/null 2>&1; then
  exec_docker_group "$PY" watch_api.py
fi
exec "$PY" watch_api.py
