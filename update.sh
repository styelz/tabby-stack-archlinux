#!/usr/bin/env bash
# Pull the latest tabby-stack commit into this install, then apply it.
#
# The live tree is the git checkout (clone into $HOME/tabby-stack, or an
# older rsync dest that this script bootstraps). Runtime data stays:
# venv, models, ComfyUI, config.yml, tabby.env.
set -euo pipefail

DEST="$(cd "$(dirname "$0")" && pwd)"
ORIGIN="${TABBY_GIT_ORIGIN:-https://github.com/styelz/tabby-stack-archlinux.git}"
UPDATE_COMFY=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--comfy]

Pull origin into this install and apply code, Python deps, and a service
reload. config.yml, tabby.env, models, and venv are left in place.

Options
  --comfy     Also git pull ComfyUI and ComfyUI-GGUF, then reinstall their
              Python requirements. Default is to leave image-gen at the
              commit the installer cloned.
  -h, --help  This text

This folder:  $DEST
Origin:       $ORIGIN
EOF
}

while (($#)); do
  case "$1" in
    --comfy) UPDATE_COMFY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

die() {
  echo "$*" >&2
  exit 1
}

if [[ "$(uname -s)" != "Linux" ]]; then
  die "Run this script on the Arch GPU host, not Windows."
fi
if [[ "${EUID}" -eq 0 ]]; then
  die "Do not run as root. Re-run as the user that owns this install."
fi
if [[ ! -f "$DEST/tabbyAPI/main.py" || ! -f "$DEST/install.sh" ]]; then
  die "This does not look like a tabby-stack install ($DEST).
Run it from the install root (default \$HOME/tabby-stack)."
fi
if ! need_cmd git; then
  die "git is not installed. On Arch: sudo pacman -S git"
fi

tracked_dirty() {
  local dir="$1"
  [[ -n "$(git -C "$dir" status --porcelain --untracked-files=no 2>/dev/null)" ]]
}

origin_branch() {
  local dir="$1"
  local branch=""
  branch="$(git -C "$dir" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  branch="${branch#origin/}"
  if [[ -z "$branch" ]]; then
    if git -C "$dir" rev-parse --verify -q origin/main >/dev/null; then
      branch=main
    elif git -C "$dir" rev-parse --verify -q origin/master >/dev/null; then
      branch=master
    fi
  fi
  printf '%s' "$branch"
}

ensure_stack_origin() {
  if ! git -C "$DEST" remote get-url origin >/dev/null 2>&1; then
    git -C "$DEST" remote add origin "$ORIGIN"
  fi
}

ff_pull() {
  local dir="$1"
  local label="$2"
  local branch=""
  if tracked_dirty "$dir"; then
    die "$label has local changes in tracked files.
Commit, stash, or restore them, then re-run. Untracked runtime files
(venv, models, ComfyUI, config.yml) are fine.

  git -C $dir status"
  fi
  echo "==> Fetching $label"
  git -C "$dir" fetch origin
  branch="$(origin_branch "$dir")"
  if [[ -z "$branch" ]]; then
    branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD)"
  fi
  [[ -n "$branch" && "$branch" != "HEAD" ]] || die "Could not determine the branch for $label."
  echo "==> Fast-forward $label to origin/$branch"
  git -C "$dir" merge --ff-only "origin/$branch"
}

if [[ -d "$DEST/.git" ]]; then
  ensure_stack_origin
  ff_pull "$DEST" "tabby-stack"
else
  echo "==> No .git here — bootstrapping from $ORIGIN"
  git -C "$DEST" init
  ensure_stack_origin
  git -C "$DEST" fetch origin
  branch="$(origin_branch "$DEST")"
  [[ -n "$branch" ]] || die "Could not find origin/main or origin/master at $ORIGIN."
  echo "==> Checking out origin/$branch (tracked files only; venv/models/ComfyUI stay)"
  if ! git -C "$DEST" checkout -f -B "$branch" "origin/$branch"; then
    echo "==> Existing files blocked checkout; resetting tracked paths to origin/$branch"
    git -C "$DEST" reset --hard "origin/$branch"
  fi
fi

if [[ "$UPDATE_COMFY" -eq 1 ]]; then
  export TABBY_UPDATE_COMFY=1
  if [[ -d "$DEST/ComfyUI/.git" ]]; then
    ff_pull "$DEST/ComfyUI" "ComfyUI"
  else
    echo "WARNING: $DEST/ComfyUI is not a git checkout; skipping ComfyUI pull." >&2
  fi
  if [[ -d "$DEST/ComfyUI/custom_nodes/ComfyUI-GGUF/.git" ]]; then
    ff_pull "$DEST/ComfyUI/custom_nodes/ComfyUI-GGUF" "ComfyUI-GGUF"
  else
    echo "WARNING: ComfyUI-GGUF is not a git checkout; skipping its pull." >&2
  fi
fi

echo "==> Applying update (pip, models skip-existing, restart)"
exec bash "$DEST/install.sh" --update
