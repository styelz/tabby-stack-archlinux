#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-screenshot.png}"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$DIR/save_clipboard_image.py" "$DEST"
fi
if command -v python >/dev/null 2>&1; then
  exec python "$DIR/save_clipboard_image.py" "$DEST"
fi
echo "python3 is required" >&2
exit 1
