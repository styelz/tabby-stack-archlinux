#!/usr/bin/env bash
# Install TabbyAPI + ComfyUI on Arch. Weights are copied from an optional
# local cache (USB or a folder you point at) or downloaded from Hugging Face.
# Re-run skips files that already exist. The git tree does not ship LLMs.
# To pull later changes on the install itself, run update.sh (this script --update).
set -euo pipefail

STACK_ROOT="$(cd "$(dirname "$0")" && pwd)"
TABBY_SRC="$STACK_ROOT/tabbyAPI"
SCRIPT_DIR="$TABBY_SRC/deploy/arch"
CATALOG="$SCRIPT_DIR/models.json"
FETCH_MODELS="$SCRIPT_DIR/fetch_models.py"

EMBED_NAME="Qwen3-Embedding-0.6B"
# Official Arch python is 3.14; python312 is AUR-only. Match the first-boot workaround.
PYENV_VER="3.12.5"

BACKTITLE="tabby-stack Arch installer"
TUI=""
USE_TUI=0
INTERACTIVE=1
UPDATE_MODE=0

usage_install() {
  cat <<EOF
Usage: $(basename "$0") [--update]

  (no args)   Interactive or env-driven install / re-run
  --update    Apply code and deps after git pull. Prefer: bash update.sh
              Reuses tabby.env; does not overwrite config.yml or tabby.env.
              Does not pacman -Syu; only installs missing OS packages.
  -h, --help  This text
EOF
}

while (($#)); do
  case "$1" in
    --update) UPDATE_MODE=1; TABBY_NONINTERACTIVE=1; shift ;;
    -h|--help) usage_install; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage_install >&2
      exit 2
      ;;
  esac
done

prompt() {
  local __var="$1"
  local __msg="$2"
  local __default="$3"
  local __value=""
  read -r -p "${__msg} [${__default}]: " __value || true
  printf -v "$__var" '%s' "${__value:-$__default}"
}

ui_cancel() {
  echo "Installer cancelled."
  exit 1
}

# dialog (ncurses) if available, else whiptail, else printed how-to + read.
tui_cmd() {
  if need_cmd dialog; then
    TUI=dialog
  elif need_cmd whiptail; then
    TUI=whiptail
  else
    TUI=""
  fi
}

ensure_dialog() {
  tui_cmd
  if [[ -n "$TUI" ]]; then
    return 0
  fi
  if [[ "$INTERACTIVE" -eq 0 ]] || [[ ! -t 0 ]]; then
    return 0
  fi
  echo "==> Installing dialog (ncurses menus and how-to screens)..."
  sudo pacman -S --needed --noconfirm dialog || true
  tui_cmd
}

ui_msg() {
  local title="$1"
  local text="$2"
  local height="${3:-20}"
  local width="${4:-74}"
  if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
    dialog --backtitle "$BACKTITLE" --title "$title" --msgbox "$text" "$height" "$width" || ui_cancel
  elif [[ "$USE_TUI" -eq 1 && "$TUI" == whiptail ]]; then
    whiptail --backtitle "$BACKTITLE" --title "$title" --msgbox "$text" "$height" "$width" || ui_cancel
  else
    echo
    echo "=== $title ==="
    echo "$text"
    echo
  fi
}

ui_input() {
  local title="$1"
  local text="$2"
  local default="$3"
  local out=""
  if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
    out="$(dialog --backtitle "$BACKTITLE" --title "$title" --stdout --inputbox "$text" 18 74 "$default")" || ui_cancel
  elif [[ "$USE_TUI" -eq 1 && "$TUI" == whiptail ]]; then
    out="$(whiptail --backtitle "$BACKTITLE" --title "$title" --inputbox "$text" 18 74 "$default" 3>&1 1>&2 2>&3)" || ui_cancel
  else
    # stdout is captured by the caller; the screen text must go to stderr.
    {
      echo
      echo "=== $title ==="
      echo "$text"
      echo
    } >&2
    read -r -p "Value [${default}]: " out || true
    out="${out:-$default}"
  fi
  printf '%s' "$out"
}

ui_menu() {
  local title="$1"
  local text="$2"
  shift 2
  local out=""
  if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
    out="$(dialog --backtitle "$BACKTITLE" --title "$title" --stdout --menu "$text" 20 74 8 "$@")" || ui_cancel
  elif [[ "$USE_TUI" -eq 1 && "$TUI" == whiptail ]]; then
    out="$(whiptail --backtitle "$BACKTITLE" --title "$title" --menu "$text" 20 74 8 "$@" 3>&1 1>&2 2>&3)" || ui_cancel
  else
    # stdout is captured by the caller; the screen text must go to stderr.
    {
      echo
      echo "=== $title ==="
      echo "$text"
      echo
    } >&2
    local i=1 tag
    local tags=()
    while (($#)); do
      tag="$1"
      tags+=("$tag")
      printf "  %s) %s — %s\n" "$i" "$tag" "$2" >&2
      shift 2
      i=$((i + 1))
    done
    local choice=""
    read -r -p "Choice [1]: " choice || true
    choice="${choice:-1}"
    if [[ "$choice" =~ ^[0-9]+$ ]] && ((choice >= 1 && choice <= ${#tags[@]})); then
      out="${tags[$((choice - 1))]}"
    else
      out="$choice"
    fi
  fi
  printf '%s' "$out"
}

ui_yesno() {
  local title="$1"
  local text="$2"
  local default_yes="${3:-1}"
  if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
    local extra=()
    [[ "$default_yes" -eq 0 ]] && extra=(--defaultno)
    dialog --backtitle "$BACKTITLE" --title "$title" "${extra[@]}" --yesno "$text" 16 74
    return $?
  elif [[ "$USE_TUI" -eq 1 && "$TUI" == whiptail ]]; then
    local extra=()
    [[ "$default_yes" -eq 0 ]] && extra=(--defaultno)
    whiptail --backtitle "$BACKTITLE" --title "$title" "${extra[@]}" --yesno "$text" 16 74
    return $?
  else
    local yn="Y/n"
    [[ "$default_yes" -eq 0 ]] && yn="y/N"
    echo
    echo "=== $title ==="
    echo "$text"
    echo
    local ans=""
    read -r -p "Continue? [$yn]: " ans || true
    ans="${ans:-$([[ "$default_yes" -eq 1 ]] && echo y || echo n)}"
    [[ "$ans" =~ ^[Yy] ]]
  fi
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

# Free GiB on the filesystem that will hold a path that may not exist yet.
free_gib() {
  local p="$1"
  while [[ -n "$p" && ! -d "$p" ]]; do
    p="$(dirname "$p")"
  done
  df -P "$p" 2>/dev/null | awk 'NR==2 {print int($4 / 1048576)}'
}

port_in_use() {
  local port="$1"
  if need_cmd ss; then
    ss -ltn 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {found=1} END {exit !found}'
  else
    return 1
  fi
}

# Poll until GET /health reports status healthy (LLM reload ~65s).
wait_for_tabby_health() {
  local port="${TABBY_NETWORK_PORT:-5000}"
  local url="http://127.0.0.1:${port}/health"
  local tries="${TABBY_HEALTH_TRIES:-180}"
  local i body
  for ((i = 1; i <= tries; i++)); do
    body="$(curl -sf "$url" 2>/dev/null || true)"
    if [[ "$body" == *'"status":"healthy"'* || "$body" == *'"status": "healthy"'* ]]; then
      echo "API healthy at $url (${i}s)." >> "${INSTALL_LOG:-/dev/null}"
      append_update_log "API healthy at $url (${i}s)."
      return 0
    fi
    sleep 1
  done
  echo "Timed out after ${tries}s waiting for $url" >> "${INSTALL_LOG:-/dev/null}"
  append_update_log "Timed out after ${tries}s waiting for $url"
  [[ -n "$body" ]] && echo "Last body: $body" >> "${INSTALL_LOG:-/dev/null}"
  return 1
}

load_tabby_env_file() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0
  # shellcheck disable=SC1090
  set -a
  . "$env_file"
  set +a
}

INSTALL_LOG=""
GAUGE_PID=""
GAUGE_FIFO=""
GAUGE_DIR=""
GAUGE_MODE=""
SUDO_KEEPALIVE_PID=""
INSTALL_FAILED=0

progress_start() {
  mkdir -p "$DEST"
  INSTALL_LOG="$DEST/tabby-install.log"
  if [[ "${TABBY_NVIDIA_REBOOT_DONE:-}" == 1 && -f "$INSTALL_LOG" ]]; then
    {
      echo
      echo "tabby-stack install resume $(date -Iseconds) (after NVIDIA reboot)"
      echo "dest=$DEST tabby=$DEST_TABBY comfy=$DEST_COMFY"
      echo "cache=${WIN_ROOT:-} models=$MODEL_SET api=$API_URL"
      echo
    } >> "$INSTALL_LOG"
  else
    {
      echo "tabby-stack install $(date -Iseconds)"
      echo "dest=$DEST tabby=$DEST_TABBY comfy=$DEST_COMFY"
      echo "cache=${WIN_ROOT:-} models=$MODEL_SET api=$API_URL"
      echo
    } > "$INSTALL_LOG"
  fi
  if [[ "${TABBY_INSTALL_VERBOSE:-}" == 1 ]]; then
    GAUGE_MODE="verbose"
    return 0
  fi
  if [[ -t 1 ]] && need_cmd dialog; then
    # mktemp -d, not a file we delete and re-create: /tmp is world-writable and
    # the gap between rm and mkfifo is a symlink race.
    GAUGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tabby-gauge.XXXXXX")"
    GAUGE_FIFO="$GAUGE_DIR/gauge"
    mkfifo -m 600 "$GAUGE_FIFO"
    local gauge_title="Installing tabby-stack"
    [[ "$UPDATE_MODE" -eq 1 ]] && gauge_title="Updating tabby-stack"
    dialog --backtitle "$BACKTITLE" --title "$gauge_title" \
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

append_update_log() {
  if [[ -n "${TABBY_UPDATE_LOG:-}" ]]; then
    printf '%s\n' "$1" >> "$TABBY_UPDATE_LOG"
  fi
}

progress() {
  local pct="$1" msg="$2"
  if [[ -n "$INSTALL_LOG" ]]; then
    printf '%s\n' "==> [$pct%] $msg" >> "$INSTALL_LOG"
  fi
  append_update_log "==> [$pct%] $msg"
  case "${GAUGE_MODE:-}" in
    dialog)
      printf 'XXX\n%s\n%s\nXXX\n' "$pct" "$msg" >&3 || true
      ;;
    text)
      local fill=$((pct / 2))
      printf '\r\033[K[%s%s] %3d%%  %s' \
        "$(printf '%*s' "$fill" '' | tr ' ' '#')" \
        "$(printf '%*s' $((50 - fill)) '')" \
        "$pct" "$msg"
      ;;
    verbose)
      echo "==> $msg"
      ;;
  esac
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
  if [[ -n "${SUDO_KEEPALIVE_PID:-}" ]]; then
    kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
    wait "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
    SUDO_KEEPALIVE_PID=""
  fi
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
      printf '\n'
      ;;
  esac
  GAUGE_MODE=""
  GAUGE_PID=""
  GAUGE_FIFO=""
  GAUGE_DIR=""
}

progress_fail() {
  local rc="${1:-1}"
  INSTALL_FAILED=1
  progress_stop
  echo
  echo "Install failed. Last lines of ${INSTALL_LOG:-the log}:"
  [[ -n "$INSTALL_LOG" && -f "$INSTALL_LOG" ]] && tail -n 40 "$INSTALL_LOG"
  echo
  echo "Full log: ${INSTALL_LOG:-}"
  append_update_log "Install failed. Full log: ${INSTALL_LOG:-}"
  exit "$rc"
}

run_quiet() {
  if [[ "${GAUGE_MODE:-}" == "verbose" ]]; then
    "$@"
    return
  fi
  if ! "$@" >>"$INSTALL_LOG" 2>&1; then
    local rc=$?
    echo "Command failed ($rc): $*" >> "$INSTALL_LOG"
    append_update_log "Command failed ($rc): $*"
    progress_fail "$rc"
  fi
}

RESUME_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/tabby-stack"

nvidia_smi_ok() {
  nvidia-smi >/dev/null 2>&1
}

pci_has_nvidia() {
  if need_cmd lspci; then
    lspci 2>/dev/null | grep -qi nvidia
  else
    return 0
  fi
}

try_load_nvidia() {
  sudo -n modprobe nvidia >/dev/null 2>&1 || true
  sudo -n modprobe nvidia_uvm >/dev/null 2>&1 || true
  nvidia_smi_ok
}

write_resume_env() {
  local f="$1"
  mkdir -p "$(dirname "$f")"
  # Subshell: umask is not function-scoped and would otherwise apply to every
  # later file the installer writes.
  (
  umask 077
  {
    echo "TABBY_NONINTERACTIVE=1"
    echo "TABBY_NVIDIA_REBOOT_DONE=1"
    printf 'TABBY_INSTALL_ROOT=%q\n' "$DEST"
    printf 'TABBY_CACHE=%q\n' "${WIN_ROOT-}"
    printf 'TABBY_MODELS=%q\n' "$MODEL_SET"
    printf 'TABBY_NETWORK_HOST=%q\n' "$TABBY_NETWORK_HOST"
    printf 'TABBY_NETWORK_PORT=%q\n' "$TABBY_NETWORK_PORT"
    printf 'COMFYUI_URL=%q\n' "$COMFYUI_URL"
    printf 'TABBY_PUBLIC_BASE=%q\n' "${TABBY_PUBLIC_BASE-}"
    printf 'TABBY_SSH_REMOTE=%q\n' "${TABBY_SSH_REMOTE-}"
    printf 'TABBY_SSH_FORWARD=%q\n' "${TABBY_SSH_FORWARD-}"
    printf 'TABBY_SSH_KEY=%q\n' "${TABBY_SSH_KEY-}"
    printf 'TABBY_INSTALL_VERBOSE=%q\n' "${TABBY_INSTALL_VERBOSE-}"
    printf 'TABBY_INSTALL_SH=%q\n' "$DEST/install.sh"
  } > "$f"
  )
}

write_resume_launch() {
  mkdir -p "$RESUME_DIR"
  cat > "$RESUME_DIR/resume-launch.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
RESUME_ENV="${XDG_CONFIG_HOME:-$HOME/.config}/tabby-stack/install-resume.env"
LOCK="${XDG_CONFIG_HOME:-$HOME/.config}/tabby-stack/install-resume.lock"
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "tabby-stack install resume is already running."
  exit 0
fi
if [[ ! -f "$RESUME_ENV" ]]; then
  exit 0
fi
# shellcheck disable=SC1090
set -a
. "$RESUME_ENV"
set +a
if [[ "${1:-}" != "--in-term" && "${1:-}" != "--headless" && ! -t 1 ]]; then
  if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    self="$(readlink -f "$0" 2>/dev/null || echo "$0")"
    for cmd in kgx gnome-terminal konsole xfce4-terminal mate-terminal \
               lxterminal tilix kitty alacritty wezterm xterm; do
      command -v "$cmd" >/dev/null 2>&1 || continue
      case "$cmd" in
        kgx|gnome-terminal|tilix) exec "$cmd" -- bash "$self" --in-term ;;
        konsole|xfce4-terminal|mate-terminal|lxterminal|alacritty|wezterm|xterm|kitty)
          exec "$cmd" -e bash "$self" --in-term ;;
      esac
    done
  fi
fi
exec bash "${TABBY_INSTALL_SH:?missing TABBY_INSTALL_SH}"
EOF
  chmod 755 "$RESUME_DIR/resume-launch.sh"
}

install_resume_hooks() {
  write_resume_env "$RESUME_DIR/install-resume.env"
  write_resume_env "$DEST/tabby-install-resume.env"
  write_resume_launch
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/tabby-stack-install-resume.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=tabby-stack install resume
Comment=Finish tabby-stack after the NVIDIA driver reboot
Exec=$RESUME_DIR/resume-launch.sh
X-GNOME-Autostart-enabled=true
Terminal=false
EOF
  local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$unit_dir"
  cat > "$unit_dir/tabby-install-resume.service" <<EOF
[Unit]
Description=Resume tabby-stack install after NVIDIA driver reboot
After=network-online.target
Wants=network-online.target
ConditionPathExists=$RESUME_DIR/install-resume.env

[Service]
Type=oneshot
ExecStart=$RESUME_DIR/resume-launch.sh --headless
TimeoutStartSec=infinity

[Install]
WantedBy=default.target
EOF
  sudo -n loginctl enable-linger "$USER" >/dev/null 2>&1 || true
  if [[ -n "${XDG_RUNTIME_DIR:-}" ]] && need_cmd systemctl; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user enable tabby-install-resume.service >/dev/null 2>&1 || true
  fi
}

clear_install_resume() {
  # Whole directory, not named files: it also holds install-resume.lock.
  rm -rf "$RESUME_DIR"
  rm -f "$HOME/.config/autostart/tabby-stack-install-resume.desktop" \
        "${DEST:-}/tabby-install-resume.env"
  if [[ -n "${XDG_RUNTIME_DIR:-}" ]] && need_cmd systemctl; then
    systemctl --user disable --now tabby-install-resume.service >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/tabby-install-resume.service"
}

RSYNC_EXCLUDES=(
  --exclude 'venv/'
  --exclude 'models/'
  --exclude 'ComfyUI/'
  --exclude 'pasted-images/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude 'logs/'
  --exclude 'build/'
  --exclude '*.egg-info/'
  --exclude '.pytest_cache/'
  --exclude '*.log'
  --exclude 'config.yml'
  --exclude 'tabby.env'
  --exclude 'deploy/arch/tabby.env'
  --exclude 'tabbyAPI/deploy/arch/tabby.env'
  --exclude 'HOW-TO-ARCH.txt'
  --exclude 'CURSOR.md'
  --exclude 'HANDOFF.md'
  --exclude '.cursor/'
  --exclude 'api_tokens.yml'
  --exclude 'ui_users.json'
  --exclude 'ui_sessions.json'
  --exclude 'tabbyAPI/ui_users.json'
  --exclude 'tabbyAPI/ui_sessions.json'
)

# Copy the git tree (including .git when present) to the install root so the
# live copy can git pull. Skip when dest is already this checkout.
# Runtime dirs and secrets listed above are left alone.
sync_tabby_sources_to_dest() {
  mkdir -p "$DEST" "$DEST_TABBY"
  local src_abs dest_abs
  src_abs="$(cd "$STACK_ROOT" && pwd)"
  dest_abs="$(cd "$DEST" && pwd)"
  if [[ "$src_abs" != "$dest_abs" ]]; then
    rsync -a "${RSYNC_EXCLUDES[@]}" "$STACK_ROOT/" "$DEST/"
  fi
  local script
  for script in install.sh uninstall.sh update.sh; do
    [[ -f "$STACK_ROOT/$script" ]] || continue
    if [[ "$STACK_ROOT/$script" -ef "$DEST/$script" ]]; then
      chmod 755 "$DEST/$script"
    else
      install -m 755 "$STACK_ROOT/$script" "$DEST/$script"
    fi
  done
}

schedule_nvidia_reboot() {
  local delay="${TABBY_REBOOT_DELAY:-300}"
  echo "NVIDIA driver installed but not loaded; scheduling reboot + resume." >> "$INSTALL_LOG"
  sync_tabby_sources_to_dest >>"$INSTALL_LOG" 2>&1 || progress_fail
  install_resume_hooks
  progress_stop
  trap - EXIT
  local mins=$((delay / 60))
  local msg
  msg="The NVIDIA driver package is installed, but the kernel module is not
loaded yet. That is normal on the first driver install. Reboot is
only used in this case — not for other install failures.

This computer will reboot in ${mins} minutes (${delay} seconds).
Enter / OK reboots now.  Ctrl+C cancels.

After reboot the installer resumes automatically with your saved
answers (no questions again):
  • at boot, via the user systemd unit tabby-install-resume
    (linger is enabled so it can start without a login)
  • or when you log into a desktop, a terminal opens and continues

Install root:  ${DEST}
Resume with:   bash ${DEST}/install.sh
Log:           ${INSTALL_LOG}

If you chose a USB or other weights cache, remount it after reboot
(or missing files will download from Hugging Face).

If resume does not start, run the command above. After a successful
install the resume hooks are removed."
  if [[ "$INTERACTIVE" -eq 1 ]]; then
    if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
      dialog --backtitle "$BACKTITLE" --title "NVIDIA driver — reboot required" \
        --timeout "$delay" --msgbox "$msg" 24 74 || true
    else
      echo
      echo "=== NVIDIA driver — reboot required ==="
      echo "$msg"
      echo
      sleep "$delay"
    fi
  else
    echo
    echo "NVIDIA driver — reboot required"
    echo "$msg"
    echo
    sleep "$delay"
  fi
  if ! sudo -n reboot; then
    echo "Could not reboot. Reboot this machine, then: bash $DEST/install.sh"
    exit 1
  fi
  exit 0
}

pkg_exists() {
  pacman -Si "$1" >/dev/null 2>&1
}

# Arch removed the proprietary `nvidia` package (590+ / Dec 2025). Official
# repos ship nvidia-open. nvidia-open does not Provide the name `nvidia`, so
# falling back to pacman -S nvidia fails with "target not found: nvidia".
nvidia_kernel_pkg() {
  if pkg_exists nvidia-open; then
    printf '%s\n' nvidia-open
  elif pkg_exists nvidia; then
    printf '%s\n' nvidia
  else
    return 1
  fi
}

init_pyenv() {
  export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
  if [[ -d "$PYENV_ROOT/bin" ]]; then
    export PATH="$PYENV_ROOT/bin:$PATH"
  fi
  if need_cmd pyenv; then
    eval "$(pyenv init - bash)"
  fi
}

ensure_sudo() {
  if [[ "${EUID}" -eq 0 ]]; then
    echo "Do not run as root. Re-run as your user."
    echo "If sudo is missing, the script will ask for the root password once to install it."
    exit 1
  fi
  if need_cmd sudo && sudo -n true 2>/dev/null; then
    return 0
  fi
  if need_cmd sudo && sudo -v; then
    return 0
  fi
  echo
  echo "==> sudo is not installed or not usable (common on a fresh Arch install)."
  echo "    Enter the root password to install sudo and allow $USER to use it."
  su -c "set -euo pipefail
    pacman -Sy --needed --noconfirm sudo
    usermod -aG wheel ${USER}
    mkdir -p /etc/sudoers.d
    printf '%s\\n' '${USER} ALL=(ALL:ALL) ALL' > /etc/sudoers.d/10-${USER}
    chmod 440 /etc/sudoers.d/10-${USER}
  "
  hash -r 2>/dev/null || true
  if ! need_cmd sudo || ! sudo -v; then
    echo "sudo is still not usable. Run: newgrp wheel"
    echo "Then re-run this script."
    exit 1
  fi
  echo "sudo is ready."
}

ensure_python312() {
  init_pyenv
  if need_cmd python3.12; then
    PY=python3.12
    return 0
  fi
  if [[ -x "${PYENV_ROOT:-$HOME/.pyenv}/versions/$PYENV_VER/bin/python" ]]; then
    PY="${PYENV_ROOT:-$HOME/.pyenv}/versions/$PYENV_VER/bin/python"
    return 0
  fi

  if need_cmd yay; then
    echo "==> Installing python312 from the AUR (yay)..."
    yay -S --needed --noconfirm python312 || true
  elif need_cmd paru; then
    echo "==> Installing python312 from the AUR (paru)..."
    paru -S --needed --noconfirm python312 || true
  fi
  hash -r 2>/dev/null || true
  if need_cmd python3.12; then
    PY=python3.12
    return 0
  fi

  echo
  echo "==> Arch repos only ship current Python (3.14). python312 is not in pacman."
  echo "    Installing pyenv and Python $PYENV_VER (do not use system 3.13/3.14)."
  if ! need_cmd pyenv; then
    curl https://pyenv.run -fsS | bash
  fi
  init_pyenv
  if ! need_cmd pyenv; then
    echo "pyenv install failed (curl https://pyenv.run)."
    return 1
  fi
  local line_root='export PYENV_ROOT="$HOME/.pyenv"'
  local line_path='[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"'
  local line_init='eval "$(pyenv init - bash)"'
  touch "$HOME/.bashrc"
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [[ -f "$rc" ]] || continue
    if ! grep -Fq 'PYENV_ROOT' "$rc"; then
      printf '\n%s\n%s\n%s\n' "$line_root" "$line_path" "$line_init" >> "$rc"
    fi
  done
  if [[ ! -x "$PYENV_ROOT/versions/$PYENV_VER/bin/python" ]]; then
    echo "    Compiling Python $PYENV_VER (several minutes)..."
    pyenv install -s "$PYENV_VER"
  fi
  # Deliberately no `pyenv global`: the venvs below use the absolute path, and
  # repointing the user's default python is not this installer's business.
  if [[ -x "$PYENV_ROOT/versions/$PYENV_VER/bin/python" ]]; then
    PY="$PYENV_ROOT/versions/$PYENV_VER/bin/python"
    return 0
  fi
  echo "Python 3.12 is required for Tabby cu12 / ExLlamaV3 wheels."
  echo "pyenv install $PYENV_VER failed."
  return 1
}

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Run this script on Arch Linux, not Windows."
  exit 1
fi
if [[ ! -f /etc/arch-release ]]; then
  echo "This installer expects Arch Linux (pacman)."
  exit 1
fi
if [[ "${EUID}" -eq 0 ]]; then
  echo "Do not run as root. Re-run as your user."
  echo "If sudo is missing, the script will ask for the root password once to install it."
  exit 1
fi
if [[ ! -f "$TABBY_SRC/pyproject.toml" || ! -f "$TABBY_SRC/main.py" ]]; then
  echo "Cannot find TabbyAPI at $TABBY_SRC (missing pyproject.toml or main.py)."
  echo "Run: bash install.sh  (from the tabby-stack root)"
  exit 1
fi
if [[ ! -f "$CATALOG" || ! -f "$FETCH_MODELS" ]]; then
  echo "Missing $CATALOG or $FETCH_MODELS."
  exit 1
fi

# Resume after an NVIDIA driver reboot (hooks or a manual re-run).
# update.sh must not pick up a leftover resume env.
if [[ "$UPDATE_MODE" -eq 0 && -z "${TABBY_NVIDIA_REBOOT_DONE:-}" && -f "${XDG_CONFIG_HOME:-$HOME/.config}/tabby-stack/install-resume.env" ]]; then
  # shellcheck disable=SC1090
  set -a
  . "${XDG_CONFIG_HOME:-$HOME/.config}/tabby-stack/install-resume.env"
  set +a
fi
if [[ "${TABBY_NVIDIA_REBOOT_DONE:-}" == 1 ]]; then
  echo "Resuming tabby-stack install after the NVIDIA driver reboot."
fi

# Env-driven install: skip menus when the three knobs are already set.
if [[ "${TABBY_NONINTERACTIVE:-}" == 1 ]] || [[ ! -t 0 ]]; then
  INTERACTIVE=0
elif [[ -n "${TABBY_INSTALL_ROOT:-}" && -n "${TABBY_MODELS:-}" ]]; then
  INTERACTIVE=0
fi
ensure_sudo
if [[ "$INTERACTIVE" -eq 1 ]]; then
  ensure_dialog
  if [[ -n "$TUI" && -t 0 && -t 1 ]]; then
    USE_TUI=1
  fi
fi

DEFAULT_CACHE=""

# Expand a leading ~ and make the path absolute. A relative dest would end up
# in the systemd unit as a relative WorkingDirectory and fail at boot.
abs_path() {
  local p="$1"
  case "$p" in
    "~") p="$HOME" ;;
    "~/"*) p="$HOME/${p#\~/}" ;;
  esac
  [[ "$p" == /* ]] || p="$PWD/$p"
  printf '%s' "$p"
}

dest_is_sane() {
  case "$DEST" in
    "" | "/" | "$HOME" | /usr | /usr/* | /etc | /etc/* | /var | /var/* | /boot | /boot/*)
      return 1
      ;;
  esac
  return 0
}

apply_choices() {
  DEST="$(abs_path "${DEST%/}")"
  DEST="${DEST%/}"
  WIN_ROOT="${WIN_ROOT%/}"
  if [[ -n "$WIN_ROOT" ]]; then
    WIN_ROOT="$(abs_path "$WIN_ROOT")"
    WIN_ROOT="${WIN_ROOT%/}"
  fi
  WIN_TABBY=""
  if [[ -n "$WIN_ROOT" ]]; then
    WIN_TABBY="${WIN_ROOT}/tabbyAPI"
  fi
  DEST_TABBY="${DEST}/tabbyAPI"
  DEST_COMFY="${DEST}/ComfyUI"
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535))
}

# Non-loopback IPv4 this host would use on the LAN. Empty if none.
# Always returns 0 so set -e does not abort the installer.
lan_ipv4() {
  local ip=""
  if need_cmd ip; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{
      for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }
    }')" || true
    if [[ -z "$ip" ]]; then
      ip="$(ip -4 -o addr show scope global 2>/dev/null | awk 'NR==1 {gsub(/\/.*/, "", $4); print $4}')" || true
    fi
  fi
  if [[ -z "$ip" ]] && need_cmd hostname; then
    ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | awk '
      /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $0 !~ /^127\./ { print; exit }
    ')" || true
  fi
  case "$ip" in
    "" | 127.* | 0.0.0.0) ip="" ;;
  esac
  if [[ "$ip" == *:* ]]; then
    ip=""
  fi
  printf '%s' "$ip"
  return 0
}

# Extra global IPv4s besides the primary, space-separated. Always returns 0.
lan_ipv4_extras() {
  local primary="$1"
  [[ -z "$primary" ]] && return 0
  need_cmd ip || return 0
  ip -4 -o addr show scope global 2>/dev/null | awk -v primary="$primary" '{
    gsub(/\/.*/, "", $4)
    if ($4 == "" || $4 == primary || index($4, ":")) next
    if (n++) printf " "
    printf "%s", $4
  }' || true
  return 0
}

apply_network_defaults() {
  TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"
  TABBY_NETWORK_PORT="${TABBY_NETWORK_PORT:-5000}"
  COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
  local hostport="${COMFYUI_URL#*://}"
  hostport="${hostport%%/*}"
  COMFY_LISTEN_HOST="${hostport%%:*}"
  COMFY_LISTEN_PORT="${hostport##*:}"
  [[ -n "$COMFY_LISTEN_HOST" ]] || COMFY_LISTEN_HOST="127.0.0.1"
  if [[ "$COMFY_LISTEN_PORT" == "$hostport" ]] || ! valid_port "$COMFY_LISTEN_PORT"; then
    COMFY_LISTEN_PORT=8188
  fi
  TABBY_PUBLIC_BASE="${TABBY_PUBLIC_BASE:-}"
  TABBY_SSH_REMOTE="${TABBY_SSH_REMOTE:-}"
  TABBY_SSH_FORWARD="${TABBY_SSH_FORWARD:-127.0.0.1:12345:127.0.0.1:${TABBY_NETWORK_PORT}}"
  TABBY_SSH_KEY="${TABBY_SSH_KEY:-$HOME/.ssh/id_ed25519}"
  API_URL="http://${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}"
}

write_tabby_env() {
  local env_file="$1"
  mkdir -p "$(dirname "$env_file")"
  cat > "$env_file" <<EOF
COMFYUI_DIR=$DEST_COMFY
COMFYUI_URL=$COMFYUI_URL
TABBY_PUBLIC_BASE=$TABBY_PUBLIC_BASE
TABBY_INSTALL_ROOT=$DEST
TABBY_NETWORK_HOST=$TABBY_NETWORK_HOST
TABBY_NETWORK_PORT=$TABBY_NETWORK_PORT
EOF
  if [[ -n "$TABBY_SSH_REMOTE" ]]; then
    cat >> "$env_file" <<EOF
TABBY_SSH_REMOTE=$TABBY_SSH_REMOTE
TABBY_SSH_FORWARD=$TABBY_SSH_FORWARD
TABBY_SSH_KEY=$TABBY_SSH_KEY
EOF
  fi
}

cache_on_dest() {
  [[ -n "$WIN_ROOT" && ( "$DEST" == "$WIN_ROOT" || "$DEST" == "$WIN_ROOT"/* || "$DEST_TABBY" == "$WIN_TABBY" ) ]]
}

DEFAULT_DEST="$HOME/tabby-stack"

if [[ "$INTERACTIVE" -eq 0 ]]; then
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    DEST="${TABBY_INSTALL_ROOT:-$STACK_ROOT}"
    DEST="$(abs_path "${DEST%/}")"
    DEST="${DEST%/}"
    load_tabby_env_file "$DEST/tabbyAPI/deploy/arch/tabby.env"
    DEST="$(abs_path "${TABBY_INSTALL_ROOT:-$DEST}")"
    DEST="${DEST%/}"
  else
    DEST="${TABBY_INSTALL_ROOT:-$DEFAULT_DEST}"
  fi
  if [[ -n "${TABBY_CACHE+x}" ]]; then
    WIN_ROOT="$TABBY_CACHE"
  else
    WIN_ROOT="$DEFAULT_CACHE"
  fi
  MODEL_SET="${TABBY_MODELS:-core}"
  apply_choices
  apply_network_defaults
  if [[ "$MODEL_SET" != "core" && "$MODEL_SET" != "all" ]]; then
    echo "Model set must be core or all (got $MODEL_SET)."
    exit 1
  fi
  if ! valid_port "$TABBY_NETWORK_PORT"; then
    echo "TABBY_NETWORK_PORT must be 1-65535 (got $TABBY_NETWORK_PORT)."
    exit 1
  fi
  if ! dest_is_sane; then
    echo "Refusing to install into $DEST. Pick a dedicated folder, e.g. $HOME/tabby-stack."
    exit 1
  fi
  if [[ "$UPDATE_MODE" -eq 1 && ! -x "$DEST_TABBY/venv/bin/python" ]]; then
    echo "No TabbyAPI venv at $DEST_TABBY."
    echo "Run bash update.sh from the install root (default \$HOME/tabby-stack),"
    echo "not from a source checkout that has not been installed."
    exit 1
  fi
  if cache_on_dest; then
    echo "Arch dest must not be the weights cache mount."
    echo "  Cache:     $WIN_ROOT"
    echo "  Arch dest: $DEST"
    echo "Use the Arch disk, e.g. $HOME/tabby-stack or /data/tabby-stack"
    exit 1
  fi
else
  ui_msg "What this installer does" \
"tabby-stack: local OpenAI-compatible API for coding and agents,
plus ComfyUI image generation on Arch. Any client that speaks /v1
works — Cursor is one example.

Use gpt-4o as the model name in your editor, and leave it.
That is not ChatGPT — it is only a name. Many editors sandbox
or block tools unless they see a known OpenAI name. The GPU
still runs the local model you switched to.

Needed
  • Arch Linux, your user (not root), internet
  • NVIDIA GPU (docs assume 12 GB)
  • Python 3.12 — this script installs it (pyenv ${PYENV_VER} if needed)
  • sudo — installed for you if missing (root password once)

What you get
  • TabbyAPI on http://127.0.0.1:5000/v1  (model name: gpt-4o — leave it)
  • ComfyUI on http://127.0.0.1:8188 after “switch to comfy”
  • linger so Tabby starts at boot with no login
  • if the NVIDIA driver needs a reboot, this script reboots and resumes

Models are not in git. They are copied from an optional local cache
or downloaded from Hugging Face.

Prefer cloning this repo into the install root (default \$HOME/tabby-stack)
so later you can run update.sh there instead of a second clone.

Source: ${TABBY_SRC}
More detail: ${SCRIPT_DIR}/README.md

Next screens ask where to install, whether you have a cache,
which model set to fetch, and the API / tunnel URLs."

  while true; do
    DEST="$(ui_input "1 / 6  — Arch install root" \
"Linux disk folder that will contain tabbyAPI/ and ComfyUI/.

Examples
  ${HOME}/tabby-stack  →  ${HOME}/tabby-stack/tabbyAPI  and  ${HOME}/tabby-stack/ComfyUI
  /data/tabby-stack    →  /data/tabby-stack/tabbyAPI   and  /data/tabby-stack/ComfyUI

Do NOT use a USB or other removable mount as the install root.
Those mounts are only a weights cache on a later screen.

Default is \$HOME/tabby-stack." \
"${TABBY_INSTALL_ROOT:-$DEFAULT_DEST}")"
    DEST="${DEST:-$DEFAULT_DEST}"

    cache_choice="$(ui_menu "2 / 6  — Weights cache" \
"If weights already live on a USB copy of tabby-stack or another
folder, this script copies them instead of re-downloading.

Mount the USB first if you want that option:
  sudo pacman -S --needed ntfs-3g
  sudo mkdir -p /mnt/usb
  sudo mount /dev/sdXN /mnt/usb
  (you should see /mnt/usb/tabby-stack/tabbyAPI)

Leave the cache empty to download from Hugging Face." \
      none "Download from Hugging Face (no cache)" \
      usb "Use /mnt/usb/tabby-stack (USB copy)" \
      custom "Type another path")"

    case "$cache_choice" in
      none) WIN_ROOT="" ;;
      usb) WIN_ROOT="/mnt/usb/tabby-stack" ;;
      custom)
        WIN_ROOT="$(ui_input "Weights cache path" \
"Folder that contains tabbyAPI/models and ComfyUI/models.

Examples
  /mnt/usb/tabby-stack
  /data/tabby-weights

Blank = download from Hugging Face." \
"${TABBY_CACHE:-$DEFAULT_CACHE}")"
        ;;
      *) WIN_ROOT="$cache_choice" ;;
    esac

    if [[ -n "$WIN_ROOT" && ! -d "$WIN_ROOT/tabbyAPI" ]]; then
      if ! ui_yesno "Cache not found" \
"No tabbyAPI folder at:
  ${WIN_ROOT}/tabbyAPI

Typical cause: the USB is not mounted, or the path is wrong.

Yes = continue and download missing files from Hugging Face.
No = go back and pick another cache." 0; then
        continue
      fi
    fi

    default_set="core"
    if [[ -n "$WIN_ROOT" && -d "$WIN_ROOT/tabbyAPI/models" ]]; then
      default_set="all"
    fi
    MODEL_SET="$(ui_menu "3 / 6  — Model set" \
"Which weights to copy or download. Re-run later to add more; existing
files are skipped.

core  — enough to chat and generate images (smaller download)
        • qwen 9B  (switch to qwen)  daily coding
        • Flux Schnell drafts + Qwen-Image (text / posters / UI)
        • Qwen3-Embedding-0.6B on CPU

all   — every “switch to …” profile (needs more disk and VRAM)
        • core, plus qwen35, qwen36, gemma, gemma26, glm
        • Gemma may be gated: huggingface-cli login or HF_TOKEN

Recommended first install: core. Default here: ${default_set}." \
      core "qwen 9B + Flux + Qwen-Image + embedder" \
      all "every switch-to profile (incl. 27B / 35B / Gemma)")"
    MODEL_SET="${MODEL_SET:-$default_set}"

    if [[ "$MODEL_SET" == "all" ]]; then
      ui_msg "Gemma / Hugging Face" \
"The “all” set includes Gemma weights that Hugging Face may gate.

If a later download returns 401 or 403:
  huggingface-cli login
  or:  export HF_TOKEN=...
  then re-run this installer (finished files are skipped).

You do not need a token for qwen / Flux / Qwen-Image."
    fi

    apply_choices
    apply_network_defaults
    if [[ "$MODEL_SET" != "core" && "$MODEL_SET" != "all" ]]; then
      ui_msg "Invalid model set" "Model set must be core or all (got ${MODEL_SET})."
      continue
    fi
    if ! dest_is_sane; then
      ui_msg "Invalid install root" \
"Refusing to install into:
  ${DEST}

That is your home directory or a system folder. Pick a dedicated
folder such as ${HOME}/tabby-stack or /data/tabby-stack."
      continue
    fi
    if cache_on_dest; then
      ui_msg "Invalid paths" \
"Arch dest must not be the weights cache mount.

  Cache:     ${WIN_ROOT}
  Arch dest: ${DEST}

Use the Linux disk, for example ${HOME}/tabby-stack or /data/tabby-stack."
      continue
    fi

    TABBY_NETWORK_HOST="$(ui_input "4 / 6  — TabbyAPI listen host" \
"Address TabbyAPI binds on. Clients (and Cursor) use this host.

  127.0.0.1  — this machine only (usual)
  0.0.0.0    — other devices on the LAN can connect

Do not put a public hostname here." \
"${TABBY_NETWORK_HOST}")"
    TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"

    TABBY_NETWORK_PORT="$(ui_input "4 / 6  — TabbyAPI listen port" \
"TCP port for the API. Default 5000.

Health:  http://${TABBY_NETWORK_HOST}:PORT/health
Cursor:  http://${TABBY_NETWORK_HOST}:PORT/v1" \
"${TABBY_NETWORK_PORT}")"
    TABBY_NETWORK_PORT="${TABBY_NETWORK_PORT:-5000}"
    if ! valid_port "$TABBY_NETWORK_PORT"; then
      ui_msg "Invalid port" "The listen port must be a number from 1 to 65535 (got ${TABBY_NETWORK_PORT})."
      TABBY_NETWORK_PORT=5000
      continue
    fi

    LAN_IP="$(lan_ipv4)"
    LAN_HINT=""
    if [[ -n "$LAN_IP" ]]; then
      LAN_HINT="
This machine:  http://${LAN_IP}:8188"
      LAN_EXTRAS="$(lan_ipv4_extras "$LAN_IP")"
      if [[ -n "$LAN_EXTRAS" ]]; then
        LAN_HINT+="  (also ${LAN_EXTRAS})"
      fi
    fi
    COMFYUI_URL="$(ui_input "4 / 6  — ComfyUI URL" \
"HTTP URL for ComfyUI after “switch to comfy”.

Usual value:  http://127.0.0.1:8188${LAN_HINT}
Change this only if ComfyUI will listen somewhere else." \
"${COMFYUI_URL}")"
    COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"

    TABBY_PUBLIC_BASE="$(ui_input "5 / 6  — Public API base URL" \
"Optional URL written into image links and the public gallery.

Examples
  https://api.example.com/v1
  https://chat.example.com/api/v1

Blank = local only (http://${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}/v1).
Leave blank if you do not have a reverse proxy or tunnel." \
"${TABBY_PUBLIC_BASE}")"

    TABBY_SSH_REMOTE="$(ui_input "5 / 6  — Reverse SSH tunnel" \
"Optional SSH target that forwards a remote port to TabbyAPI.

Example:  user@host.example

Blank = no tunnel (API stays on this machine).
If you set a host, the next screens ask for the forward spec and key." \
"${TABBY_SSH_REMOTE}")"
    if [[ -n "$TABBY_SSH_REMOTE" ]]; then
      TABBY_SSH_FORWARD="$(ui_input "5 / 6  — SSH forward spec" \
"ssh -R spec: remote listen → local TabbyAPI.

Default matches the listen port you chose (${TABBY_NETWORK_PORT})." \
"${TABBY_SSH_FORWARD:-127.0.0.1:12345:127.0.0.1:${TABBY_NETWORK_PORT}}")"
      TABBY_SSH_FORWARD="${TABBY_SSH_FORWARD:-127.0.0.1:12345:127.0.0.1:${TABBY_NETWORK_PORT}}"
      TABBY_SSH_KEY="$(ui_input "5 / 6  — SSH private key" \
"Key file for ${TABBY_SSH_REMOTE}.

The installer copies ~/.ssh/id_ed25519 from a cache if present.
Use that path unless your key has another name." \
"${TABBY_SSH_KEY:-$HOME/.ssh/id_ed25519}")"
      TABBY_SSH_KEY="${TABBY_SSH_KEY:-$HOME/.ssh/id_ed25519}"
    else
      TABBY_SSH_FORWARD=""
      TABBY_SSH_KEY=""
    fi
    apply_network_defaults
    # apply_network_defaults fills empty SSH defaults; keep tunnel off if remote is blank
    if [[ -z "$TABBY_SSH_REMOTE" ]]; then
      TABBY_SSH_FORWARD=""
      TABBY_SSH_KEY=""
    fi
    API_URL="http://${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}"

    if ui_yesno "6 / 6  — Confirm" \
"Start the install with these settings?

  Arch dest:     ${DEST}
  TabbyAPI:      ${DEST_TABBY}
  ComfyUI:       ${DEST_COMFY}
  Weights cache: ${WIN_ROOT:- (none — Hugging Face)}
  Model set:     ${MODEL_SET}
  API:           ${API_URL}
  ComfyUI URL:   ${COMFYUI_URL}
  Public base:   ${TABBY_PUBLIC_BASE:- (none — local only)}
  SSH remote:    ${TABBY_SSH_REMOTE:- (none — no tunnel)}
  SSH forward:   ${TABBY_SSH_FORWARD:- (n/a)}
  SSH key:       ${TABBY_SSH_KEY:- (n/a)}

This can take a long time (Python 3.12, pip wheels, model files).
Re-run is safe: a good venv and existing weights are skipped.

Yes = begin.  No = change answers.  Esc = cancel." \
      1; then
      break
    fi
  done
fi

apply_network_defaults
if [[ -z "$TABBY_SSH_REMOTE" ]]; then
  TABBY_SSH_FORWARD=""
  TABBY_SSH_KEY=""
fi
API_URL="http://${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}"

# Rough floor: venvs and CUDA wheels are ~15 GiB, weights are the rest.
NEED_GIB=45
[[ "$MODEL_SET" == "all" ]] && NEED_GIB=90
HAVE_GIB="$(free_gib "$DEST")"
if [[ -n "$HAVE_GIB" ]] && ((HAVE_GIB < NEED_GIB)); then
  SPACE_MSG="Only ${HAVE_GIB} GiB free on the filesystem holding ${DEST}.
The \"${MODEL_SET}\" set plus the two Python environments needs about
${NEED_GIB} GiB. The install will fail part-way through a download.

Free some space, or pick the \"core\" set / a different disk."
  if [[ "$INTERACTIVE" -eq 1 ]]; then
    if ! ui_yesno "Low disk space" "$SPACE_MSG

Continue anyway?" 0; then
      exit 1
    fi
  else
    echo "WARNING: $SPACE_MSG"
  fi
fi

OUR_UNIT_ACTIVE=0
if need_cmd systemctl && systemctl --user is-active --quiet tabbyapi 2>/dev/null; then
  OUR_UNIT_ACTIVE=1
fi
if [[ "$OUR_UNIT_ACTIVE" -eq 0 ]] && port_in_use "$TABBY_NETWORK_PORT"; then
  PORT_MSG="Something is already listening on port ${TABBY_NETWORK_PORT}.
That is usually an older TabbyAPI (systemctl --user status tabbyapi) or a
manual start.sh. Two copies would both load the model and exhaust the GPU.

The installer will not start the service while the port is taken."
  if [[ "$INTERACTIVE" -eq 1 ]]; then
    if ! ui_yesno "Port ${TABBY_NETWORK_PORT} is in use" "$PORT_MSG

Continue installing anyway?" 0; then
      exit 1
    fi
  else
    echo "WARNING: $PORT_MSG"
  fi
fi

PACKAGES=(
  sudo
  nvidia-utils
  python
  python-pip
  git
  rsync
  openssh
  ntfs-3g
  base-devel
  cmake
  ninja
  pkgconf
  wget
  curl
  which
  procps-ng
  pciutils
  iproute2
  ca-certificates
  openssl
  zlib
  xz
  tk
  readline
  sqlite
  bzip2
  ncurses
  gdbm
  libffi
  libjpeg-turbo
  libpng
  libtiff
  libwebp
  freetype2
  openjpeg2
  lcms2
  ffmpeg
  mesa
  libglvnd
  dos2unix
  dialog
  nodejs
  npm
  docker
)

ensure_sudo
if need_cmd sudo; then
  ( while true; do sudo -n true && sleep 50 || exit; done ) >/dev/null 2>&1 &
  SUDO_KEEPALIVE_PID=$!
fi
progress_start
trap 'rc=$?; if [[ "$INSTALL_FAILED" -eq 0 && "$rc" -ne 0 ]]; then progress_fail "$rc"; else progress_stop; fi' EXIT

NVIDIA_DRIVER_INSTALLED_NOW=0
if [[ "$UPDATE_MODE" -eq 0 ]]; then
  progress 4 "Syncing packages"
  run_quiet sudo -n pacman -Sy --noconfirm
fi

if nvidia_smi_ok; then
  :
else
  nvidia_kmod=$(nvidia_kernel_pkg) || {
    echo "NVIDIA kernel package not in the repos (tried nvidia-open, then nvidia)." >> "$INSTALL_LOG"
    progress_fail 1
  }
  PACKAGES+=("$nvidia_kmod")
  echo "NVIDIA kernel package: $nvidia_kmod" >> "$INSTALL_LOG"
  NVIDIA_DRIVER_INSTALLED_NOW=1
  if pacman -Q linux >/dev/null 2>&1; then
    PACKAGES+=(linux-headers)
  fi
  if pacman -Q linux-lts >/dev/null 2>&1; then
    PACKAGES+=(linux-lts-headers)
  fi
fi

if [[ "$UPDATE_MODE" -eq 1 ]]; then
  # Do not pacman -Sy / upgrade installed pkgs. That is pacman -Syu.
  # Only install names the stack needs that are not on the system yet.
  progress 10 "Checking packages"
  missing=()
  for p in "${PACKAGES[@]}"; do
    pacman -Q "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if ((${#missing[@]})); then
    echo "Installing missing packages: ${missing[*]}" >> "$INSTALL_LOG"
    run_quiet sudo -n pacman -S --needed --noconfirm "${missing[@]}"
  fi
else
  progress 10 "Installing packages"
  run_quiet sudo -n pacman -S --needed --noconfirm "${PACKAGES[@]}"
fi

if ! need_cmd nvidia-smi; then
  echo "nvidia-smi not found after package install." >> "$INSTALL_LOG"
  progress_fail 1
fi
if nvidia_smi_ok; then
  :
elif try_load_nvidia; then
  echo "Loaded NVIDIA kernel module without reboot." >> "$INSTALL_LOG"
elif [[ "${TABBY_NVIDIA_REBOOT_DONE:-}" == 1 ]]; then
  echo "nvidia-smi still fails after the NVIDIA reboot." >> "$INSTALL_LOG"
  nvidia-smi >>"$INSTALL_LOG" 2>&1 || true
  progress_fail 1
elif [[ "$NVIDIA_DRIVER_INSTALLED_NOW" -eq 1 ]] && pci_has_nvidia; then
  if [[ "$UPDATE_MODE" -eq 1 ]]; then
    echo "nvidia-smi failed during update; not rebooting." >> "$INSTALL_LOG"
    progress_fail 1
  fi
  schedule_nvidia_reboot
else
  echo "nvidia-smi failed and a reboot will not help." >> "$INSTALL_LOG"
  nvidia-smi >>"$INSTALL_LOG" 2>&1 || true
  progress_fail 1
fi
run_quiet nvidia-smi

enable_docker() {
  sudo -n systemctl enable --now docker >>"$INSTALL_LOG" 2>&1 || \
    echo "WARNING: could not enable docker.service" >> "$INSTALL_LOG"
  sudo -n usermod -aG docker "$USER" >>"$INSTALL_LOG" 2>&1 || true
}

drop_codebox_containers() {
  local ids=()
  if need_cmd docker; then
    mapfile -t ids < <(docker ps -aq --filter label=tabby.stack=code 2>/dev/null || true)
    if ((${#ids[@]})); then
      docker rm -f "${ids[@]}" >>"$INSTALL_LOG" 2>&1 || \
        sudo -n docker rm -f "${ids[@]}" >>"$INSTALL_LOG" 2>&1 || true
    fi
  fi
}

build_codebox_image() {
  local df="$DEST_TABBY/ui/codebox/Dockerfile"
  local dir="$DEST_TABBY/ui/codebox"
  [[ -f "$df" ]] || return 0
  if sudo -n docker build -t tabby-stack-code:local -f "$df" "$dir" >>"$INSTALL_LOG" 2>&1; then
    drop_codebox_containers
    return 0
  fi
  if need_cmd docker && docker build -t tabby-stack-code:local -f "$df" "$dir" >>"$INSTALL_LOG" 2>&1; then
    drop_codebox_containers
    return 0
  fi
  echo "WARNING: tabby-stack-code image build failed" >> "$INSTALL_LOG"
}

enable_docker

progress 16 "Checking Python 3.12"
if ! ensure_python312 >>"$INSTALL_LOG" 2>&1; then
  progress_fail 1
fi
PY_VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PY_VER" != "3.12" ]]; then
  echo "Need Python 3.12 (got $PY_VER)." >> "$INSTALL_LOG"
  progress_fail 1
fi

progress 22 "Syncing tabby-stack sources"
run_quiet sync_tabby_sources_to_dest
if need_cmd dos2unix; then
  run_quiet find "$DEST_TABBY" -type f -name '*.sh' -exec dos2unix -q {} +
else
  run_quiet find "$DEST_TABBY" -type f -name '*.sh' -exec sed -i 's/\r$//' {} +
fi
progress 24 "Building Code sandbox image"
build_codebox_image
chmod 755 "$DEST_TABBY/deploy/arch/run-api.sh" 2>/dev/null || true
if [[ -d "$DEST_TABBY/venv/Scripts" ]]; then
  rm -rf "$DEST_TABBY/venv"
fi
PATCH_SPAWN="$DEST_TABBY/deploy/arch/patch_linux_spawn.py"
if [[ ! -f "$PATCH_SPAWN" ]]; then
  PATCH_SPAWN="$SCRIPT_DIR/patch_linux_spawn.py"
fi
if [[ -f "$PATCH_SPAWN" ]]; then
  run_quiet "$PY" "$PATCH_SPAWN" "$DEST_TABBY"
fi

CREATED_CONFIG=0
if [[ ! -f "$DEST_TABBY/config.yml" && -f "$DEST_TABBY/config_sample.yml" ]]; then
  cp "$DEST_TABBY/config_sample.yml" "$DEST_TABBY/config.yml"
  CREATED_CONFIG=1
fi
DEFAULT_MODEL="Qwen3.5-9B-exl3-4.00bpw"
# Seed model_name only when we just created config.yml. A re-run or update
# must not throw away the profile the user last switched to.
if [[ "$CREATED_CONFIG" -eq 1 ]]; then
  "$PY" -c "
from pathlib import Path
p = Path(r'''$DEST_TABBY/config.yml''')
text = p.read_text(encoding='utf-8')
out = []
for line in text.splitlines(True):
    if line.startswith('  model_name:'):
        out.append('  model_name: $DEFAULT_MODEL\n')
    elif line.startswith('  embedding_model_name:'):
        out.append('  embedding_model_name: $EMBED_NAME\n')
    else:
        out.append(line)
p.write_text(''.join(out), encoding='utf-8')
" >>"$INSTALL_LOG" 2>&1 || progress_fail
fi
mkdir -p "$DEST_TABBY/model_profiles" "$DEST_TABBY/models"
# Seed only on a first install; a re-run must not throw away the profile the
# user last switched to.
if [[ ! -s "$DEST_TABBY/model_profiles/last.json" ]]; then
  printf '%s\n' '{"profile": "qwen"}' > "$DEST_TABBY/model_profiles/last.json"
fi
if [[ ! -s "$DEST_TABBY/model_profiles/gpu_mode.json" ]]; then
  printf '%s\n' '{"mode": "llm", "profile": "qwen"}' > "$DEST_TABBY/model_profiles/gpu_mode.json"
fi

progress 28 "Installing ComfyUI"
if [[ ! -f "$DEST_COMFY/main.py" ]]; then
  run_quiet git clone https://github.com/comfyanonymous/ComfyUI.git "$DEST_COMFY"
fi
mkdir -p "$DEST_COMFY/models/checkpoints"
if [[ -d "$DEST_COMFY/venv/Scripts" ]]; then
  rm -rf "$DEST_COMFY/venv"
fi

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
SSH_KEY_NAME="$(basename "${TABBY_SSH_KEY:-id_ed25519}")"
if [[ -n "$WIN_ROOT" && -f "$WIN_ROOT/.ssh/$SSH_KEY_NAME" ]]; then
  cp -f "$WIN_ROOT/.ssh/$SSH_KEY_NAME" "$HOME/.ssh/$SSH_KEY_NAME"
  chmod 600 "$HOME/.ssh/$SSH_KEY_NAME"
  if need_cmd dos2unix; then
    dos2unix -q "$HOME/.ssh/$SSH_KEY_NAME" 2>/dev/null || dos2unix "$HOME/.ssh/$SSH_KEY_NAME"
  else
    sed -i 's/\r$//' "$HOME/.ssh/$SSH_KEY_NAME"
  fi
  if [[ -f "$WIN_ROOT/.ssh/${SSH_KEY_NAME}.pub" ]]; then
    cp -f "$WIN_ROOT/.ssh/${SSH_KEY_NAME}.pub" "$HOME/.ssh/${SSH_KEY_NAME}.pub"
    if need_cmd dos2unix; then
      dos2unix -q "$HOME/.ssh/${SSH_KEY_NAME}.pub" 2>/dev/null || dos2unix "$HOME/.ssh/${SSH_KEY_NAME}.pub"
    else
      sed -i 's/\r$//' "$HOME/.ssh/${SSH_KEY_NAME}.pub"
    fi
  fi
fi

tabby_venv_ok() {
  [[ -x "$DEST_TABBY/venv/bin/python" ]] && \
    "$DEST_TABBY/venv/bin/python" -c "import torch, exllamav3; assert torch.cuda.is_available()"
}

progress 40 "TabbyAPI Python environment"
if ! tabby_venv_ok; then
  rm -rf "$DEST_TABBY/venv"
  run_quiet "$PY" -m venv "$DEST_TABBY/venv"
  run_quiet "$DEST_TABBY/venv/bin/python" -m pip install -U pip setuptools wheel packaging
  run_quiet env -C "$DEST_TABBY" "$DEST_TABBY/venv/bin/python" -m pip install -U ".[cu12]"
  if ! tabby_venv_ok; then
    echo "TabbyAPI venv check failed (torch/exllamav3/CUDA)." >> "$INSTALL_LOG"
    progress_fail 1
  fi
elif [[ "$UPDATE_MODE" -eq 1 ]]; then
  progress 45 "Updating TabbyAPI Python packages"
  run_quiet env -C "$DEST_TABBY" "$DEST_TABBY/venv/bin/python" -m pip install -U ".[cu12]"
fi
if [[ "$UPDATE_MODE" -eq 1 ]] || ! "$DEST_TABBY/venv/bin/python" -c "import infinity_emb, sentence_transformers" >/dev/null 2>&1; then
  progress 55 "TabbyAPI extras"
  run_quiet env -C "$DEST_TABBY" "$DEST_TABBY/venv/bin/python" -m pip install -U ".[extras]"
fi
run_quiet "$DEST_TABBY/venv/bin/python" -m pip install -U 'numpy>=2.1.0'
if [[ -f "$DEST_TABBY/ui/fetch_monaco.py" ]]; then
  progress 56 "Monaco editor"
  run_quiet "$DEST_TABBY/venv/bin/python" "$DEST_TABBY/ui/fetch_monaco.py"
fi
if [[ "$UPDATE_MODE" -eq 0 && -x "$DEST_TABBY/venv/bin/python" && -f "$DEST_TABBY/switch_model.py" ]]; then
  ( cd "$DEST_TABBY" && "$DEST_TABBY/venv/bin/python" switch_model.py qwen --no-load ) >>"$INSTALL_LOG" 2>&1 || true
fi

comfy_venv_ok() {
  [[ -x "$DEST_COMFY/venv/bin/python" ]] && \
    "$DEST_COMFY/venv/bin/python" -c "import torch; assert torch.cuda.is_available()"
}

# Comfy kitchen CUDA kernels need a PyTorch build for CUDA 13.0+.
comfy_torch_cu13() {
  [[ -x "$DEST_COMFY/venv/bin/python" ]] && \
    "$DEST_COMFY/venv/bin/python" -c "import torch; v=torch.version.cuda or '0'; assert tuple(int(x) for x in v.split('.')[:2]) >= (13, 0)"
}

install_comfy_torch() {
  # cu130 torch first: requirements.txt would otherwise pull the PyPI build and
  # this would download ~2.5 GB of wheels twice.
  run_quiet "$DEST_COMFY/venv/bin/python" -m pip install -U torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu130
  # Drop leftover CUDA 12 NVIDIA wheels so start.sh does not prepend their lib dirs.
  # Those packages share nvidia/{cudnn,nccl,...} paths with the cu13 builds, so
  # uninstall can delete the CUDA 13 .so files; put the same cu13 pins back.
  mapfile -t oldcuda < <("$DEST_COMFY/venv/bin/python" -m pip freeze | awk -F== 'tolower($1) ~ /-cu12$/ {print $1}')
  mapfile -t cu13nvidia < <("$DEST_COMFY/venv/bin/python" -m pip freeze | awk -F== 'tolower($1) ~ /^nvidia-.*-cu13$/ {print}')
  if ((${#oldcuda[@]})); then
    run_quiet "$DEST_COMFY/venv/bin/python" -m pip uninstall -y "${oldcuda[@]}"
    if ((${#cu13nvidia[@]})); then
      run_quiet "$DEST_COMFY/venv/bin/python" -m pip install --force-reinstall --no-deps \
        "${cu13nvidia[@]}" --index-url https://download.pytorch.org/whl/cu130
    fi
  fi
}

progress 62 "ComfyUI Python environment"
if ! comfy_venv_ok; then
  rm -rf "$DEST_COMFY/venv"
  run_quiet "$PY" -m venv "$DEST_COMFY/venv"
  run_quiet "$DEST_COMFY/venv/bin/python" -m pip install -U pip setuptools wheel
  install_comfy_torch
  if [[ -f "$DEST_COMFY/requirements.txt" ]]; then
    run_quiet "$DEST_COMFY/venv/bin/python" -m pip install -r "$DEST_COMFY/requirements.txt"
  fi
  if ! comfy_venv_ok || ! comfy_torch_cu13; then
    echo "ComfyUI venv check failed (torch CUDA 13)." >> "$INSTALL_LOG"
    progress_fail 1
  fi
elif ! comfy_torch_cu13; then
  install_comfy_torch
  if ! comfy_torch_cu13; then
    echo "ComfyUI torch CUDA 13 upgrade failed." >> "$INSTALL_LOG"
    progress_fail 1
  fi
elif [[ "${TABBY_UPDATE_COMFY:-}" == 1 && -f "$DEST_COMFY/requirements.txt" ]]; then
  progress 65 "Updating ComfyUI Python packages"
  run_quiet "$DEST_COMFY/venv/bin/python" -m pip install -U -r "$DEST_COMFY/requirements.txt"
fi

cat > "$DEST_COMFY/start.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
extra=()
for lib in venv/lib/python*/site-packages/nvidia/*/lib; do
  [[ -d "$lib" ]] && extra+=("$lib")
done
if ((${#extra[@]})); then
  joined=$(IFS=:; echo "${extra[*]}")
  export LD_LIBRARY_PATH="${joined}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
EOF
printf 'exec ./venv/bin/python -u main.py --listen %s --port %s "$@"\n' \
  "$COMFY_LISTEN_HOST" "$COMFY_LISTEN_PORT" >> "$DEST_COMFY/start.sh"
chmod +x "$DEST_COMFY/start.sh"

progress 78 "ComfyUI-GGUF"
mkdir -p "$DEST_COMFY/custom_nodes"
if [[ ! -f "$DEST_COMFY/custom_nodes/ComfyUI-GGUF/nodes.py" ]]; then
  run_quiet git clone --depth 1 https://github.com/city96/ComfyUI-GGUF "$DEST_COMFY/custom_nodes/ComfyUI-GGUF"
fi
if [[ -f "$DEST_COMFY/custom_nodes/ComfyUI-GGUF/requirements.txt" ]]; then
  run_quiet "$DEST_COMFY/venv/bin/python" -m pip install -U -r "$DEST_COMFY/custom_nodes/ComfyUI-GGUF/requirements.txt"
fi

progress 84 "Copying model weights"
mkdir -p \
  "$DEST_TABBY/models" \
  "$DEST_COMFY/models/checkpoints" \
  "$DEST_COMFY/models/unet" \
  "$DEST_COMFY/models/text_encoders" \
  "$DEST_COMFY/models/vae" \
  "$DEST_COMFY/models/loras"
DEST_CATALOG="$DEST_TABBY/deploy/arch/models.json"
[[ -f "$DEST_CATALOG" ]] || DEST_CATALOG="$CATALOG"
DEST_FETCH="$DEST_TABBY/deploy/arch/fetch_models.py"
[[ -f "$DEST_FETCH" ]] || DEST_FETCH="$FETCH_MODELS"
FETCH_ARGS=(
  --catalog "$DEST_CATALOG"
  --tabby "$DEST_TABBY"
  --comfy "$DEST_COMFY"
  --set "$MODEL_SET"
)
if [[ -n "$WIN_ROOT" && -d "$WIN_ROOT" ]]; then
  FETCH_ARGS+=(--cache "$WIN_ROOT")
fi
run_quiet "$DEST_TABBY/venv/bin/python" "$DEST_FETCH" "${FETCH_ARGS[@]}"

progress 94 "Writing config and enabling service"
install_unless_same() {
  local mode="$1" src="$2" dest="$3"
  if [[ "$src" -ef "$dest" ]]; then
    chmod "$mode" "$dest" || true
    return 0
  fi
  install -m "$mode" "$src" "$dest"
}

if [[ -f "$SCRIPT_DIR/start.sh" ]]; then
  run_quiet install_unless_same 755 "$SCRIPT_DIR/start.sh" "$DEST/start.sh"
else
  echo "Missing $SCRIPT_DIR/start.sh" >> "$INSTALL_LOG"
  progress_fail 1
fi
if [[ -f "$STACK_ROOT/AGENTS.md" ]]; then
  run_quiet install_unless_same 644 "$STACK_ROOT/AGENTS.md" "$DEST/AGENTS.md"
else
  echo "Missing $STACK_ROOT/AGENTS.md" >> "$INSTALL_LOG"
  progress_fail 1
fi
if [[ "$UPDATE_MODE" -eq 0 || ! -f "$DEST_TABBY/deploy/arch/tabby.env" ]]; then
  write_tabby_env "$DEST_TABBY/deploy/arch/tabby.env"
fi

UNIT_SRC="$DEST_TABBY/deploy/arch/tabbyapi.service"
if [[ ! -f "$UNIT_SRC" ]]; then
  UNIT_SRC="$SCRIPT_DIR/tabbyapi.service"
fi
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
sed "s|__TABBY_DIR__|$DEST_TABBY|g" "$UNIT_SRC" > "$UNIT_DIR/tabbyapi.service"

COMFY_UNIT_SRC="$DEST_TABBY/deploy/arch/comfyui.service"
if [[ ! -f "$COMFY_UNIT_SRC" ]]; then
  COMFY_UNIT_SRC="$SCRIPT_DIR/comfyui.service"
fi
if [[ -f "$COMFY_UNIT_SRC" ]]; then
  sed "s|__COMFY_DIR__|$DEST_COMFY|g" "$COMFY_UNIT_SRC" > "$UNIT_DIR/comfyui.service"
fi

if ! sudo -n loginctl enable-linger "$USER" >>"$INSTALL_LOG" 2>&1; then
  echo "WARNING: linger failed. Run: sudo loginctl enable-linger $USER" >> "$INSTALL_LOG"
fi
START_NOTE=""
if [[ -n "${XDG_RUNTIME_DIR:-}" ]] && need_cmd systemctl; then
  systemctl --user daemon-reload >>"$INSTALL_LOG" 2>&1 || true
  systemctl --user enable tabbyapi >>"$INSTALL_LOG" 2>&1 || true
  if systemctl --user is-active --quiet tabbyapi; then
    # The unit file was just rewritten for this dest; restart so it takes effect
    # instead of leaving an old process on the port.
    systemctl --user restart tabbyapi >>"$INSTALL_LOG" 2>&1 || true
  elif port_in_use "$TABBY_NETWORK_PORT"; then
    START_NOTE="Port $TABBY_NETWORK_PORT is in use by another process, so tabbyapi was enabled but not started."
    echo "WARNING: $START_NOTE" >> "$INSTALL_LOG"
  else
    systemctl --user start tabbyapi >>"$INSTALL_LOG" 2>&1 || true
  fi
fi
if [[ "$UPDATE_MODE" -eq 1 ]]; then
  progress 97 "Waiting for API health"
  if [[ -n "$START_NOTE" ]]; then
    echo "WARNING: skipping health wait ($START_NOTE)" >> "$INSTALL_LOG"
  elif ! wait_for_tabby_health; then
    echo "API did not become healthy. Check: journalctl --user -u tabbyapi -e" >> "$INSTALL_LOG"
    progress_fail 1
  fi
fi

progress 100 "Finished"
progress_stop
trap - EXIT
restore_tty
clear_install_resume

HOWTO="$DEST_TABBY/HOW-TO-ARCH.txt"
cat > "$HOWTO" <<EOF
TabbyAPI on Arch — how to use this install
==========================================
Written by install.sh. You do not need the Windows chat for this.

Paths
  Install:   $DEST
  Start:     $DEST/start.sh
  TabbyAPI:  $DEST_TABBY
  ComfyUI:   $DEST_COMFY
  Python:    $PY ($PY_VER)
  SSH key:   ${TABBY_SSH_KEY:- (none)}
  How-to:    $HOWTO
  Agents:    $DEST/AGENTS.md
  README:    $DEST_TABBY/deploy/arch/README.md

Start / stop
  Starts at boot (no login) via linger + systemctl --user enable tabbyapi
  systemctl --user enable --now tabbyapi
  systemctl --user status tabbyapi
  systemctl --user stop tabbyapi
  journalctl --user -u tabbyapi -f
  (ComfyUI lines show up there as [comfy] ...)
  linger: sudo loginctl enable-linger $USER
  check:  loginctl show-user $USER -p Linger

  API:     $API_URL
  Health:  GET $API_URL/health
  UI:      $API_URL/v1/ui   (Linux account or a Tabby-only user)
  Manual:  $DEST/start.sh

  Do not run start.bat.
  If you used a USB cache you can unmount it.

Management UI ($API_URL/v1/ui)
  Sign in with the Linux user that runs tabbyapi (admin), or a Tabby-only account.
  Chat     conversations, vision, model commands, image generation; follow-up queue
  Code     project folder on this host (Monaco, file tools, preview, container terminal)
  Status   GPU mode, occupancy, profile, health; load LLM / Comfy; restart; Update git / Update all
  Gallery  generated images (admin can see all users)
  Logs     live journalctl for TabbyAPI (and Comfy when up)
  Users    admin-only: create/reset/delete Tabby accounts (not Linux users)
  Extra users can use Chat, Code, Status, Gallery, and Logs.

  Editor coding uses your editor pointed at /v1. Browser Code is the on-host alternative.

Your editor or IDE
  Full notes (any editor):  $DEST/AGENTS.md
  Base URL:  $API_URL/v1
  Model:     gpt-4o   (leave it — not ChatGPT; else your editor or IDE may sandbox / block tools)
  Public base: ${TABBY_PUBLIC_BASE:- (none — local only)}
  SSH tunnel:  ${TABBY_SSH_REMOTE:- (none)}
  UI via tunnel: same /v1/ui path under your public /v1 prefix

Switch models (warm 12 GB: qwen ~65s; qwen35 ~3 min; comfy ~35s)
  In chat (editor or /v1/ui), send only:
    help                    full usage guide
    list models
    restart                 bounce the API; last model reloads
    switch to qwen          daily coding, 9B, faster (~65s)
    switch to qwen35        long/hard Agent (~3 min on 12 GB)
    switch to qwen36        (~85s)
    switch to gemma         (~65s)
    switch to gemma26       (~2 min)
    switch to glm           thinking; vision off on 12 GB (~15s)
    switch to comfy         images; unloads the LLM (~35s ready)
    switch to llm           free Comfy, reload last LLM (~65s)

  GPU is exclusive: LLM or Comfy, not both.
  First start loads qwen 9B (about 65s; first Linux boot may compile Triton longer).
  qwen35 can take about 3 minutes. Chat is not ComfyUI — only switch to comfy for images.
  Short messages can still be slow on qwen35 if the client sends a large agent prompt. Use qwen for daily work.

Images (clients are remote — chat and HTTP only)
  switch to comfy, wait ~35s, then a short prompt (first Flux ~3 min, Qwen-Image ~4 min)
  or one line: generate an image of a login form  (API hands off GPU, returns a URL, reloads LLM)
  or POST $API_URL/v1/images/generations   (OpenAI-shaped; b64_json + url)
  Flux Schnell: drafts (a red bicycle in the rain)
  Qwen-Image: text / posters / UI / buttons, or prefix qwen-image:
  paste a photo in the same turn for Flux img2img
  The chat reply includes a PNG URL on this API host. The markdown preview is the picture.

Embeddings (CPU, no GPU switch)
  POST $API_URL/v1/embeddings
  model: $EMBED_NAME
  stays loaded beside the LLM

If something fails
  nvidia-smi fails       installer reboots once if the new driver is not loaded;
                         if it still fails: nvidia-smi ; journalctl -k | grep -i nvidia
  USB NTFS dirty/read-only  sudo ntfsfix /dev/sdXN then remount
  missing models         re-run install.sh (downloads from Hugging Face; skips what exists)
  HF 401/403 gated       huggingface-cli login  or  export HF_TOKEN=...
  SSH key missing        optional; only for a public reverse tunnel
  SSH key CRLF / invalid  installer runs dos2unix on a cache-copied ~/.ssh/id_ed25519
  public URL dead        optional tunnel; local API is $API_URL
  systemctl --user fails export XDG_RUNTIME_DIR=/run/user/\$(id -u)
  port already in use    another TabbyAPI or a manual start.sh owns the port.
                         The GPU is exclusive, so stop the old one first:
                         systemctl --user stop tabbyapi ; ss -ltnp | grep $TABBY_NETWORK_PORT
  dies on logout        sudo loginctl enable-linger $USER   (installer does this)
  no sudo               re-run as your user; enter the root password when asked
  Python 3.13/3.14      re-run install.sh (it installs pyenv 3.12.5)
  copy interrupted       re-run install.sh (rsync resumes)
  switch 500 creationflags  re-run install.sh (patches Linux spawn) then:
                         systemctl --user restart tabbyapi
  ComfyUI is not running  you asked for chat, not images. Send switch to qwen
                         and wait; first start should already load the 9B model
  no LLM loaded          wait for startup, or send switch to qwen in chat

Update
  $DEST/update.sh              asks Update git vs Update all (dialog menu)
  $DEST/update.sh --git        git pull only; offers an API restart at the end
  $DEST/update.sh --git --restart
                              git pull, then restart tabbyapi (no prompt)
  $DEST/update.sh --no-restart skip the restart prompt on Update git
  $DEST/update.sh --all        pull, then apply deps and restart
  $DEST/update.sh --comfy      also pull ComfyUI and ComfyUI-GGUF

  This folder is the git checkout. You do not need a second clone.
  config.yml, tabby.env, models, venv, and ComfyUI weights are kept.
  If update.sh changes in the pull, it restarts itself.
  Update all reloads the API until GET /health is healthy (~65s).
  Update git offers that restart at the end; --restart skips the prompt.

Uninstall
  $DEST/uninstall.sh              stop services, then remove the install
  $DEST/uninstall.sh --dry-run    show what it would do
  $DEST/uninstall.sh --purge      also delete the model weights

  It stops the user services and any leftover process before deleting files.
  Do not just rm -rf this folder: the enabled user unit would keep a running
  process on port $TABBY_NETWORK_PORT with no files behind it, and linger
  would start it again at boot.

  Weights and generated images are kept unless you pass --purge. Packages,
  the NVIDIA driver, pyenv and ~/.ssh are never touched.

Re-run is safe. Existing weights are not downloaded again.
A code update uses update.sh, not a fresh clone.
EOF

if [[ "$UPDATE_MODE" -eq 1 ]]; then
  echo "Update finished."
  append_update_log "Update finished."
else
  echo "Install finished."
fi
[[ -n "$START_NOTE" ]] && echo "  NOTE: $START_NOTE"
echo "  API:  $API_URL"
echo "  Start: $DEST/start.sh"
echo "  Agents: $DEST/AGENTS.md"
echo "  Update: $DEST/update.sh"
echo "  Uninstall: $DEST/uninstall.sh"
echo "  Log:  $INSTALL_LOG"
echo "  How-to: $HOWTO"

if [[ "$INTERACTIVE" -eq 1 ]]; then
  ui_msg "Install finished" \
"TabbyAPI and ComfyUI are set up.
${START_NOTE:+
  NOTE: $START_NOTE
}
  API:     $API_URL
  Start:   $DEST/start.sh
  Health:  GET $API_URL/health
  Editor:  $API_URL/v1   model gpt-4o  (leave it — else your editor or IDE may sandbox / block tools)
  Agents:  $DEST/AGENTS.md
  Images:  chat “generate an image of …” or POST /v1/images/generations
  UI:      Chat, Code, Status, Gallery, Logs (Users is admin-only)

Chat phrases (send as the whole message)
  help
  list models
  restart
  switch to qwen / qwen35 / qwen36 / gemma / gemma26 / glm
  switch to comfy   then wait ~35s for images
  switch to llm     to unload Comfy

IDE / agent notes (not Cursor-only):
  ${DEST}/AGENTS.md

To remove this install later:
  ${DEST}/uninstall.sh            (stops the services first — do not rm -rf)
  ${DEST}/uninstall.sh --dry-run  to preview

To pull later git changes on this install:
  ${DEST}/update.sh

The same how-to is in:
  ${HOWTO}

Linger starts TabbyAPI at boot (no login)."
fi

