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
# git = git pull only; all = pull then install.sh --update (pip, restart).
UPDATE_KIND="${TABBY_UPDATE_KIND:-}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--git|--all] [--comfy]

Pull origin into this install. At the start a dialog asks Update git or
Update all. If this script itself changes in that pull, it re-runs so the
new update.sh is used. config.yml, tabby.env, models, and venv stay.
Does not run pacman -Syu or upgrade already-installed OS packages.

Options
  --git       Git pull only. No pip, missing OS packages, or service restart.
  --all       Pull, then apply code, Python deps, and reload tabbyapi.
  --comfy     Also git pull ComfyUI and ComfyUI-GGUF. Update all then
              reinstalls their Python requirements; git-only only pulls.
  -h, --help  This text

No flag and a TTY: dialog menu. No TTY: --all.
Or set TABBY_UPDATE_KIND=git or all.

This folder:  $DEST
Origin:       $ORIGIN
EOF
}

while (($#)); do
  case "$1" in
    --git|--files|--files-only) UPDATE_KIND=git; shift ;;
    --all|--full) UPDATE_KIND=all; shift ;;
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
  files) UPDATE_KIND=git ;;
  full) UPDATE_KIND=all ;;
esac
case "$UPDATE_KIND" in
  ""|git|all) ;;
  *)
    echo "TABBY_UPDATE_KIND must be git or all (got $UPDATE_KIND)." >&2
    exit 2
    ;;
esac

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

BACKTITLE="tabby-stack"
UPDATE_LOG=""
UI_STARTED=0
GAUGE_PID=""
GAUGE_FIFO=""
GAUGE_DIR=""
GAUGE_MODE=""

die() {
  if [[ "$UI_STARTED" -eq 1 ]]; then
    ui_fail "$*"
  fi
  echo "$*" >&2
  exit 1
}

restore_tty() {
  [[ -t 1 || -c /dev/tty ]] || return 0
  {
    command -v tput >/dev/null 2>&1 && {
      tput rmcup || true
      tput rmkx || true
      tput cnorm || true
      tput sgr0 || true
    }
    printf '\033[?1049l\033[?25h\033[m'
    stty sane
  } >/dev/tty 2>/dev/null || true
}

progress_stop() {
  case "${GAUGE_MODE:-}" in
    dialog)
      exec 3>&- || true
      wait "$GAUGE_PID" 2>/dev/null || true
      if [[ -n "$GAUGE_DIR" ]]; then
        rm -rf "$GAUGE_DIR"
      fi
      restore_tty
      ;;
    text)
      printf '\n' >/dev/tty 2>/dev/null || printf '\n'
      ;;
  esac
  GAUGE_MODE=""
  GAUGE_PID=""
  GAUGE_FIFO=""
  GAUGE_DIR=""
  UI_STARTED=0
}

progress() {
  local pct="$1" msg="$2"
  if [[ -n "$UPDATE_LOG" ]]; then
    printf '%s\n' "==> [$pct%] $msg" >> "$UPDATE_LOG"
  fi
  case "${GAUGE_MODE:-}" in
    dialog)
      printf 'XXX\n%s\n%s\nXXX\n' "$pct" "$msg" >&3 || true
      ;;
    text)
      local fill=$((pct / 2))
      printf '\r\033[K[%s%s] %3d%%  %s' \
        "$(printf '%*s' "$fill" '' | tr ' ' '#')" \
        "$(printf '%*s' $((50 - fill)) '')" \
        "$pct" "$msg" >/dev/tty
      ;;
    verbose)
      echo "==> $msg"
      ;;
  esac
}

ui_start() {
  UPDATE_LOG="$DEST/tabby-update.log"
  {
    echo "tabby-stack update $(date -Iseconds)"
    echo "dest=$DEST kind=$UPDATE_KIND comfy=$UPDATE_COMFY"
    echo
  } > "$UPDATE_LOG"
  UI_STARTED=1
  if [[ "${TABBY_INSTALL_VERBOSE:-}" == 1 ]]; then
    GAUGE_MODE="verbose"
    return 0
  fi
  if [[ -t 1 ]] && need_cmd dialog; then
    GAUGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tabby-update-gauge.XXXXXX")"
    GAUGE_FIFO="$GAUGE_DIR/gauge"
    mkfifo -m 600 "$GAUGE_FIFO"
    dialog --backtitle "$BACKTITLE" --title "Updating tabby-stack" \
      --gauge "Starting..." 8 70 0 < "$GAUGE_FIFO" &
    GAUGE_PID=$!
    exec 3>"$GAUGE_FIFO"
    GAUGE_MODE="dialog"
    return 0
  fi
  if [[ -t 1 ]]; then
    GAUGE_MODE="text"
    return 0
  fi
  GAUGE_MODE="log"
}

ui_msg() {
  local title="$1"
  local text="$2"
  if [[ -t 1 ]] && need_cmd dialog; then
    dialog --backtitle "$BACKTITLE" --title "$title" --msgbox "$text" 12 74 || true
  else
    echo
    echo "=== $title ==="
    echo "$text"
    echo
  fi
}

ui_fail() {
  local msg="$1"
  local extra=""
  progress_stop
  if [[ -n "$UPDATE_LOG" && -f "$UPDATE_LOG" ]]; then
    extra="$(tail -n 16 "$UPDATE_LOG")"
    msg="$msg

$extra

Full log: $UPDATE_LOG"
  fi
  if [[ -t 1 ]] && need_cmd dialog; then
    dialog --backtitle "$BACKTITLE" --title "Update failed" --msgbox "$msg" 20 74 || true
  else
    echo "$msg" >&2
  fi
  exit 1
}

run_git() {
  printf '+ %s\n' "$*" >> "$UPDATE_LOG"
  if ! GIT_TERMINAL_PROMPT=0 "$@" >>"$UPDATE_LOG" 2>&1; then
    local rc=$?
    echo "command failed ($rc)" >> "$UPDATE_LOG"
    die "Git command failed ($rc)."
  fi
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
  if [[ ! -t 0 || ! -t 1 ]]; then
    UPDATE_KIND=all
    echo "==> No TTY; update all (deps + restart). Pass --git for git pull only."
    return
  fi
  local out=""
  local title="Update tabby-stack"
  local text="Update git pulls new code and leaves the API running.
Update all also refreshes Python deps, installs missing OS packages, and restarts the API."
  if need_cmd dialog; then
    out="$(dialog --backtitle "tabby-stack" --title "$title" --stdout --menu "$text" 16 74 2 \
      git "Update git" \
      all "Update all")" || die "Update cancelled."
  elif need_cmd whiptail; then
    out="$(whiptail --backtitle "tabby-stack" --title "$title" --menu "$text" 16 74 2 \
      git "Update git" \
      all "Update all" 3>&1 1>&2 2>&3)" || die "Update cancelled."
  else
    echo
    echo "$title"
    echo "$text"
    echo "  1) Update git"
    echo "  2) Update all"
    echo
    local ans
    read -r -p "Choice [1/2] (default 2): " ans || die "No choice given."
    out="$ans"
  fi
  case "${out,,}" in
    git|1) UPDATE_KIND=git ;;
    all|2|"") UPDATE_KIND=all ;;
    *) die "Unknown update choice: $out" ;;
  esac
}

reexec_args() {
  local -a args=()
  if [[ "$UPDATE_KIND" == git ]]; then
    args+=(--git)
  else
    args+=(--all)
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
    printf '%s\n' "==> Removing untracked copies that already match $spec" >> "${UPDATE_LOG:-/dev/null}"
    for f in "${matches[@]}"; do
      rm -f "$dir/$f"
    done
  fi
  if ((${#conflicts[@]})); then
    bak="$(mktemp -d "${TMPDIR:-/tmp}/tabby-stack-update-untracked.XXXXXX")"
    printf '%s\n' "==> Untracked files differ from $spec; moving aside to $bak" >> "${UPDATE_LOG:-/dev/null}"
    for f in "${conflicts[@]}"; do
      mkdir -p "$bak/$(dirname "$f")"
      mv "$dir/$f" "$bak/$f"
      printf '    %s\n' "$f" >> "${UPDATE_LOG:-/dev/null}"
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
    run_git git -C "$DEST" remote add origin "$ORIGIN"
  fi
}

is_stack_wrapper() {
  case "$1" in
    install.sh|uninstall.sh|update.sh) return 0 ;;
    *) return 1 ;;
  esac
}

dirty_tracked_names() {
  local dir="$1"
  git -C "$dir" diff --name-only
  git -C "$dir" diff --cached --name-only
}

restore_head_file() {
  local dir="$1" file="$2"
  git -C "$dir" restore --source=HEAD --staged --worktree -- "$file" 2>/dev/null \
    || git -C "$dir" restore --worktree --source=HEAD -- "$file"
}

# Copy-to-live of files already on origin must not block a fast-forward.
# Real edits (content that is not on origin) still abort, except install/update
# wrappers which are held aside and put back after the merge.
take_origin_copies() {
  local dir="$1" spec="$2"
  local f
  local -A seen=()
  MATCHED_ORIGIN=()
  AHEAD_WRAPPERS=()
  REAL_EDITS=()
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    [[ -z "${seen[$f]:-}" ]] || continue
    seen[$f]=1
    [[ -f "$dir/$f" ]] || {
      REAL_EDITS+=("$f")
      continue
    }
    if git -C "$dir" cat-file -e "$spec:$f" 2>/dev/null && matches_origin_blob "$dir" "$spec" "$f"; then
      MATCHED_ORIGIN+=("$f")
      restore_head_file "$dir" "$f"
      continue
    fi
    if is_stack_wrapper "$f"; then
      AHEAD_WRAPPERS+=("$f")
    else
      REAL_EDITS+=("$f")
    fi
  done < <(dirty_tracked_names "$dir")
}

ff_pull() {
  local dir="$1"
  local label="$2"
  local branch=""
  local wrappers_tmp=""
  local wrap f
  local pct_fetch="${3:-15}"
  local pct_merge="${4:-75}"
  progress "$pct_fetch" "Fetching $label"
  run_git git -C "$dir" fetch origin
  branch="$(origin_branch "$dir")"
  if [[ -z "$branch" ]]; then
    branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD)"
  fi
  [[ -n "$branch" && "$branch" != "HEAD" ]] || die "Could not determine the branch for $label."
  take_origin_copies "$dir" "origin/$branch"
  if ((${#MATCHED_ORIGIN[@]})); then
    printf '%s\n' "==> Local copies already match origin/$branch" >> "$UPDATE_LOG"
  fi
  if ((${#AHEAD_WRAPPERS[@]})); then
    wrappers_tmp="$(mktemp -d "${TMPDIR:-/tmp}/tabby-stack-wrappers.XXXXXX")"
    for wrap in "${AHEAD_WRAPPERS[@]}"; do
      printf '%s\n' "==> Holding local $wrap (newer than origin/$branch)" >> "$UPDATE_LOG"
      cp "$dir/$wrap" "$wrappers_tmp/$wrap"
      restore_head_file "$dir" "$wrap"
    done
  fi
  if ((${#REAL_EDITS[@]})); then
    if [[ -n "$wrappers_tmp" ]]; then
      cp -a "$wrappers_tmp/." "$dir/"
      rm -rf "$wrappers_tmp"
    fi
    die "$label has local edits that are not on origin/$branch:
$(printf '  %s\n' "${REAL_EDITS[@]}")
Commit, stash, or restore them, then re-run. Copies that already match
GitHub are fine. Untracked venv, models, ComfyUI, and config.yml are fine."
  fi
  if real_tracked_diff "$dir"; then
    if [[ -n "$wrappers_tmp" ]]; then
      cp -a "$wrappers_tmp/." "$dir/"
      rm -rf "$wrappers_tmp"
    fi
    die "$label has local edits in tracked files (not just line endings).
Commit, stash, or restore them, then re-run. Untracked runtime files
(venv, models, ComfyUI, config.yml) are fine."
  fi
  if tracked_dirty "$dir"; then
    printf '%s\n' "==> Ignoring CRLF-only line-ending drift in $label" >> "$UPDATE_LOG"
    restore_crlf_only "$dir"
  fi
  clear_matching_untracked "$dir" "origin/$branch"
  progress "$pct_merge" "Fast-forward $label to origin/$branch"
  run_git git -C "$dir" merge --ff-only "origin/$branch"
  if [[ -n "$wrappers_tmp" ]]; then
    cp -a "$wrappers_tmp/." "$dir/"
    rm -rf "$wrappers_tmp"
    printf '%s\n' "==> Restored local install/update scripts" >> "$UPDATE_LOG"
  fi
}

ask_update_kind
ui_start
trap 'rc=$?; if [[ "$UI_STARTED" -eq 1 ]]; then progress_stop; fi; exit "$rc"' EXIT
BEFORE_UPDATE_SH="$(hash_ignore_cr <"$DEST/update.sh")"

if [[ -d "$DEST/.git" ]]; then
  ensure_stack_origin
  ff_pull "$DEST" "tabby-stack" 20 70
else
  progress 15 "Bootstrapping git from origin"
  run_git git -C "$DEST" init
  ensure_stack_origin
  run_git git -C "$DEST" fetch origin
  branch="$(origin_branch "$DEST")"
  [[ -n "$branch" ]] || die "Could not find origin/main or origin/master at $ORIGIN."
  progress 55 "Checking out origin/$branch"
  if ! GIT_TERMINAL_PROMPT=0 git -C "$DEST" checkout -f -B "$branch" "origin/$branch" >>"$UPDATE_LOG" 2>&1; then
    progress 70 "Resetting tracked paths to origin/$branch"
    run_git git -C "$DEST" reset --hard "origin/$branch"
  fi
fi

if [[ "$UPDATE_COMFY" -eq 1 ]]; then
  export TABBY_UPDATE_COMFY=1
  if [[ -d "$DEST/ComfyUI/.git" ]]; then
    ff_pull "$DEST/ComfyUI" "ComfyUI" 80 88
  else
    printf '%s\n' "WARNING: $DEST/ComfyUI is not a git checkout; skipping ComfyUI pull." >> "$UPDATE_LOG"
  fi
  if [[ -d "$DEST/ComfyUI/custom_nodes/ComfyUI-GGUF/.git" ]]; then
    ff_pull "$DEST/ComfyUI/custom_nodes/ComfyUI-GGUF" "ComfyUI-GGUF" 90 95
  else
    printf '%s\n' "WARNING: ComfyUI-GGUF is not a git checkout; skipping its pull." >> "$UPDATE_LOG"
  fi
fi

AFTER_UPDATE_SH="$(hash_ignore_cr <"$DEST/update.sh")"
if [[ "$BEFORE_UPDATE_SH" != "$AFTER_UPDATE_SH" ]]; then
  progress 98 "Restarting with the new update.sh"
  trap - EXIT
  progress_stop
  mapfile -t _reexec < <(reexec_args)
  exec bash "$DEST/update.sh" "${_reexec[@]}"
fi

if [[ "$UPDATE_KIND" == git ]]; then
  progress 100 "Git update finished"
  trap - EXIT
  progress_stop
  ui_msg "Update git" "Pulled the latest code. The API was not restarted.

Log: $UPDATE_LOG"
  exit 0
fi

progress 100 "Code pulled; applying deps and restart"
trap - EXIT
progress_stop
exec bash "$DEST/install.sh" --update
