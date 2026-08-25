#!/usr/bin/env bash
# Start TabbyAPI from the tabby-stack install root (not from tabbyAPI/).
# The installer copies this file to $DEST/start.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
TABBY="$ROOT/tabbyAPI"
ENV_FILE="$TABBY/deploy/arch/tabby.env"

if [[ ! -x "$TABBY/venv/bin/python" ]]; then
  echo "TabbyAPI is not installed here ($TABBY/venv is missing)."
  echo "From the tabby-stack source root run: bash install.sh"
  exit 1
fi

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet tabbyapi 2>/dev/null; then
  echo "tabbyapi is already running via systemd."
  echo "  status: systemctl --user status tabbyapi"
  echo "  stop:   systemctl --user stop tabbyapi"
  exit 0
fi

cd "$TABBY"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
export TABBY_LOG_CONSOLE_WIDTH="${TABBY_LOG_CONSOLE_WIDTH:-256}"
if [[ -w /var/run/docker.sock ]]; then
  exec "$TABBY/venv/bin/python" "$TABBY/watch_api.py" "$@"
fi
if command -v sg >/dev/null 2>&1 && sg docker -c true >/dev/null 2>&1; then
  exec sg docker -c "exec \"$TABBY/venv/bin/python\" \"$TABBY/watch_api.py\""
fi
if command -v sudo >/dev/null 2>&1 && sudo -n -u "$USER" -g docker true >/dev/null 2>&1; then
  exec sudo -n -u "$USER" -g docker "$TABBY/venv/bin/python" "$TABBY/watch_api.py" "$@"
fi
exec "$TABBY/venv/bin/python" "$TABBY/watch_api.py" "$@"
