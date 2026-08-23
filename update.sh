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
# files = git pull only; full = pull then install.sh --update (pip, restart).
UPDATE_KIND="${TABBY_UPDATE_KIND:-}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--files|--full] [--comfy]

Pull origin into this install. At the start you are asked whether to only
update files or run a full update (deps + API restart). If this script
itself changes in that pull, it re-runs so the new update.sh is used.
config.yml, tabby.env, models, and venv are left in place.
Does not run pacman -Syu or upgrade already-installed OS packages.

Options
  --files     Git pull only. No pip, missing OS packages, or service restart.
  --full      Pull, then apply code, Python deps, and reload tabbyapi.
  --comfy     Also git pull ComfyUI and ComfyUI-GGUF. Full update then
              reinstalls their Python requirements; files-only only pulls.
  -h, --help  This text

No flag and a TTY: prompt. No TTY: --full (same as older update.sh).
Or set TABBY_UPDATE_KIND=files or full.

This folder:  $DEST
Origin:       $ORIGIN
EOF
}

while (($#)); do
  case "$1" in
    --files|--files-only) UPDATE_KIND=files; shift ;;
    --full) UPDATE_KIND=full; shift ;;
    --comfy) UPDATE_COMFY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$UPDATE_KIND" in
  ""|files|full) ;;
  *)
    echo "TABBY_UPDATE_KIND must be files or full (got $UPDATE_KIND)." >&2
    exit 2
    ;;
esac

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

ask_update_kind() {
  if [[ -n "$UPDATE_KIND" ]]; then
    return
  fi
  if [[ ! -t 0 ]]; then
    UPDATE_KIND=full
    echo "==> No TTY; full update (deps + restart). Pass --files for git pull only."
    return
  fi
  echo
  echo "How do you want to update $DEST?"
  echo "  1) Files only  — git pull; leave the venv and API running"
  echo "  2) Full update — pull, refresh Python deps, install missing OS"
  echo "                   packages, restart tabbyapi, wait for /health"
  echo
  local ans
  while true; do
    read -r -p "Choice [1/2] (default 2): " ans || die "No choice given."
    case "${ans,,}" in
      ""|2|full) UPDATE_KIND=full; break ;;
      1|files) UPDATE_KIND=files; break ;;
      *) echo "Enter 1 (files) or 2 (full)." ;;
    esac
  done
}

reexec_args() {
  local -a args=()
  if [[ "$UPDATE_KIND" == files ]]; then
    args+=(--files)
  else
    args+=(--full)
  fi
  if [[ "$UPDATE_COMFY" -eq 1 ]]; then
    args+=(--comfy)
  fi
  printf '%s\n' "${args[@]}"
}

tracked_dirty() {
  local dir="$1"
  [[ -n "$(git -C "$dir" status --porcelain --untracked-files=no 2>/dev/null)" ]]
}

# Content change, not CRLF vs LF. Copy-to-live on Linux often strips CRs that
# Windows committed; that is not a local edit.
real_tracked_diff() {
  local dir="$1"
  [[ -n "$(git -C "$dir" diff --ignore-cr-at-eol 2>/dev/null)" ]] && return 0
  [[ -n "$(git -C "$dir" diff --cached --ignore-cr-at-eol 2>/dev/null)" ]] && return 0
  return 1
}

restore_crlf_only() {
  local dir="$1"
  local f
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    git -C "$dir" restore --worktree --source=HEAD -- "$f"
  done < <(git -C "$dir" diff --name-only)
}

hash_ignore_cr() {
  tr -d '\r' | git hash-object --stdin
}

matches_origin_blob() {
  local dir="$1" spec="$2" file="$3"
  local want have
  want="$(git -C "$dir" cat-file -p "$spec:$file" | hash_ignore_cr)"
  have="$(hash_ignore_cr <"$dir/$file")"
  [[ "$want" == "$have" ]]
}

# Copy-deploy leaves new repo files untracked. git merge will not overwrite them
# even when they already match origin. Older copies are moved aside; origin wins.
clear_matching_untracked() {
  local dir="$1" spec="$2"
  local f bak=""
  local -a conflicts=() matches=()
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    git -C "$dir" cat-file -e "$spec:$f" 2>/dev/null || continue
    if matches_origin_blob "$dir" "$spec" "$f"; then
      matches+=("$f")
    else
      conflicts+=("$f")
    fi
  done < <(git -C "$dir" ls-files --others --exclude-standard)
  if ((${#matches[@]})); then
    echo "==> Removing untracked copies that already match $spec"
    for f in "${matches[@]}"; do
      rm -f "$dir/$f"
    done
  fi
  if ((${#conflicts[@]})); then
    bak="$(mktemp -d "${TMPDIR:-/tmp}/tabby-stack-update-untracked.XXXXXX")"
    echo "==> Untracked files differ from $spec; moving aside to $bak"
    for f in "${conflicts[@]}"; do
      mkdir -p "$bak/$(dirname "$f")"
      mv "$dir/$f" "$bak/$f"
      echo "    $f"
    done
  fi
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
  local wrappers_tmp=""
  echo "==> Fetching $label"
  git -C "$dir" fetch origin
  branch="$(origin_branch "$dir")"
  if [[ -z "$branch" ]]; then
    branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD)"
  fi
  [[ -n "$branch" && "$branch" != "HEAD" ]] || die "Could not determine the branch for $label."
  # Newer install/update scripts copied onto the install must not block the pull.
  local wrap
  for wrap in install.sh uninstall.sh update.sh; do
    [[ -f "$dir/$wrap" ]] || continue
    [[ -n "$(git -C "$dir" diff --ignore-cr-at-eol -- "$wrap" 2>/dev/null)" ]] || continue
    if [[ -z "$wrappers_tmp" ]]; then
      wrappers_tmp="$(mktemp -d "${TMPDIR:-/tmp}/tabby-stack-wrappers.XXXXXX")"
      echo "==> Holding local $wrap (not on origin yet)"
    else
      echo "==> Holding local $wrap (not on origin yet)"
    fi
    cp "$dir/$wrap" "$wrappers_tmp/$wrap"
    git -C "$dir" restore --worktree --source=HEAD -- "$wrap"
  done
  if real_tracked_diff "$dir"; then
    if [[ -n "$wrappers_tmp" ]]; then
      cp -a "$wrappers_tmp/." "$dir/"
      rm -rf "$wrappers_tmp"
    fi
    die "$label has local edits in tracked files (not just line endings).
Commit, stash, or restore them, then re-run. Untracked runtime files
(venv, models, ComfyUI, config.yml) are fine.

  git -C $dir status"
  fi
  if tracked_dirty "$dir"; then
    echo "==> Ignoring CRLF-only line-ending drift in $label"
    restore_crlf_only "$dir"
  fi
  clear_matching_untracked "$dir" "origin/$branch"
  echo "==> Fast-forward $label to origin/$branch"
  git -C "$dir" merge --ff-only "origin/$branch"
  if [[ -n "$wrappers_tmp" ]]; then
    cp -a "$wrappers_tmp/." "$dir/"
    rm -rf "$wrappers_tmp"
    echo "==> Restored local install/update scripts"
  fi
}

ask_update_kind
BEFORE_UPDATE_SH="$(hash_ignore_cr <"$DEST/update.sh")"

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

AFTER_UPDATE_SH="$(hash_ignore_cr <"$DEST/update.sh")"
if [[ "$BEFORE_UPDATE_SH" != "$AFTER_UPDATE_SH" ]]; then
  echo "==> update.sh changed on disk; restarting with the new script"
  mapfile -t _reexec < <(reexec_args)
  exec bash "$DEST/update.sh" "${_reexec[@]}"
fi

if [[ "$UPDATE_KIND" == files ]]; then
  echo "==> Files-only update finished (no pip / API restart)."
  exit 0
fi

echo "==> Applying update (pip, models skip-existing, restart)"
exec bash "$DEST/install.sh" --update
