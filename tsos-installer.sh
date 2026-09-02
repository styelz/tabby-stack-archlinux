#!/usr/bin/env bash
# tsos-installer.sh
#
# Install Arch Linux from the official live ISO, then install tabby-stack in
# the chroot (venvs, weights) so first boot only starts the API (linger).
#
# Run as root from the Arch Linux live ISO. The target disk is wiped
# unless you pass --resume-tabby (finish install.sh on an already-mounted /mnt).
#
# Usage:
#   ./tsos-installer.sh
#   curl -fsSL https://raw.githubusercontent.com/styelz/tabby-stack-archlinux/main/tsos-installer.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/styelz/tabby-stack-archlinux/main/tsos-installer.sh | bash -s -- --no-encrypt
#
# curl | bash is supported: questions are read from /dev/tty, not from the
# download pipe. You must run it from a real console (or ssh -t). Use bash,
# not sh.

set -euo pipefail

SCRIPT_NAME="${0##*/}"
if [[ "$SCRIPT_NAME" == "bash" || "$SCRIPT_NAME" == "-bash" || "$SCRIPT_NAME" == "sh" || "$SCRIPT_NAME" == "-sh" ]]; then
  SCRIPT_NAME="tsos-installer.sh"
fi
SCRIPT_VERSION="1.0.19"

# Generic defaults. Do not default TARGET_HOSTNAME from $HOSTNAME — the live
# ISO sets HOSTNAME=archiso.
TARGET_HOSTNAME="${TARGET_HOSTNAME:-tsos}"
TARGET_USER="${TARGET_USER:-tabby}"
TIMEZONE="${TIMEZONE:-UTC}"
LOCALE="${LOCALE:-en_US.UTF-8}"
KEYMAP="${KEYMAP:-us}"
ESP_SIZE="${ESP_SIZE:-2G}"
MAPPER_NAME="${MAPPER_NAME:-root}"
ENCRYPT="${ENCRYPT:-1}"
OMARCHY_MODE="${OMARCHY_MODE:-skip}" # now | skip
OMARCHY_USER_NAME="${OMARCHY_USER_NAME:-}"
OMARCHY_USER_EMAIL="${OMARCHY_USER_EMAIL:-}"
TABBY_REPO="${TABBY_REPO:-https://github.com/styelz/tabby-stack-archlinux.git}"
TABBY_LOCAL_SRC="${TABBY_LOCAL_SRC:-}"
TABBY_MODELS="${TABBY_MODELS:-core}"
TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"
TABBY_NETWORK_PORT="${TABBY_NETWORK_PORT:-5000}"
TABBY_CACHE="${TABBY_CACHE:-}"
TABBY_PUBLIC_BASE="${TABBY_PUBLIC_BASE:-}"
TABBY_SSH_REMOTE="${TABBY_SSH_REMOTE:-}"
TABBY_SSH_FORWARD="${TABBY_SSH_FORWARD:-}"
TABBY_SSH_KEY="${TABBY_SSH_KEY:-}"
COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
DISK="${DISK:-}"
CONFIRM_WIPE="${CONFIRM_WIPE:-}"
PASSWORD="${PASSWORD:-}"
LUKS_PASSWORD="${LUKS_PASSWORD:-}"
USER_PASSWORD="${USER_PASSWORD:-}"
ROOT_PASSWORD="${ROOT_PASSWORD:-}"
DRY_RUN=0
CONFIG_PROVIDED=0
RESUME_TABBY=0
DEFAULT_DISK=/dev/sda
TUI=""
USE_TUI=0
BACKTITLE="tabby-stack OS installer"

TARGET="/mnt"
CRYPT_NAME="$MAPPER_NAME"
CACHE_STAGING=/run/tsos-weight-cache
CACHE_CHROOT_PATH=/mnt/tsos-cache
TABBY_CACHE_CHROOT=""

usage() {
  cat <<EOF
${SCRIPT_NAME} v${SCRIPT_VERSION}

Install Arch Linux (btrfs + Limine, optional LUKS) from the live ISO, then
install tabby-stack in the chroot before reboot. Omarchy is optional (now
or skip). Omarchy now requires LUKS.

USAGE
  ${SCRIPT_NAME} [options]
  curl -fsSL https://raw.githubusercontent.com/styelz/tabby-stack-archlinux/main/tsos-installer.sh | bash
  curl -fsSL https://raw.githubusercontent.com/styelz/tabby-stack-archlinux/main/tsos-installer.sh | bash -s -- [options]

With no --config file, the script asks for every setting before it runs.
It uses the same dialog menus as install.sh when dialog is available
(installed on the live ISO if needed). Press Enter to keep the default.

curl | bash needs a real terminal so the questions can be answered. Use
bash, not sh. Pass flags after bash -s -- .

OPTIONS
  --config FILE            Use FILE instead of the interactive settings prompts
  --disk PATH              Disk to wipe (default: first installable disk)
  --hostname NAME          Installed system hostname (default: tsos)
  --user NAME              Regular wheel user that runs tabby-stack (default: tabby)
  --timezone ZONE          Timezone (default: UTC)
  --locale NAME            Locale, without the leading # (default: en_US.UTF-8)
  --keymap NAME            Console keymap (default: us)
  --esp-size SIZE          EFI partition size (default: 2G)
  --encrypt                LUKS on the root partition (default)
  --no-encrypt             Unencrypted btrfs root
  --with-omarchy           Run the official Omarchy installer in the chroot (requires LUKS)
  --skip-omarchy           Do not install Omarchy (default)
  --name "FULL NAME"       Git name passed to Omarchy as OMARCHY_USER_NAME
  --email ADDR             Git email passed to Omarchy as OMARCHY_USER_EMAIL
  --models SET             Model set: core or all (asked in this UI unless --config)
  --tabby-host ADDR        TabbyAPI listen address (asked in this UI unless --config)
  --tabby-port N           TabbyAPI listen port (asked in this UI unless --config)
  --tabby-cache PATH       Optional weights cache. Asked here (before wipe)
                           so a USB under /mnt can be bind-mounted aside.
  --tabby-repo URL         Git remote to clone (default: tabby-stack-archlinux)
  --tabby-local-src PATH   Overlay this tabby-stack tree after clone (install.sh, etc.)
  --resume-tabby           Do not wipe. Finish install.sh in an already-mounted
                           system at /mnt (after a chroot install.sh failure)
  --confirm-wipe PATH      Non-interactive wipe confirmation; must equal --disk
  --password-env           Read PASSWORD / LUKS_PASSWORD / USER_PASSWORD / ROOT_PASSWORD
                           from the environment instead of prompting
  --dry-run                Print the plan and exit (does not write the disk)
  --self-test              Run built-in helper tests
  -h, --help               Show this help

ENVIRONMENT
  DISK, TARGET_HOSTNAME, TARGET_USER, TIMEZONE, LOCALE, KEYMAP, ESP_SIZE
  ENCRYPT                  1 (LUKS) or 0 (plain btrfs)
  PASSWORD                 Used for LUKS + user + root if the split passwords are unset
  LUKS_PASSWORD, USER_PASSWORD, ROOT_PASSWORD
  OMARCHY_USER_NAME, OMARCHY_USER_EMAIL, OMARCHY_MODE (now|skip)
  TABBY_REPO, TABBY_LOCAL_SRC, TABBY_MODELS, TABBY_NETWORK_HOST, TABBY_NETWORK_PORT
  TABBY_CACHE, TABBY_PUBLIC_BASE, COMFYUI_URL, HF_TOKEN

One password is used for the user, root, and disk encryption (when enabled)
unless you set the split password variables.

The live ISO's HOSTNAME (usually archiso) is ignored on purpose.

tabby-stack install.sh runs in the chroot on the live ISO (Python, venvs,
weights) and must finish before reboot. This script asks every setting
(disk, user, cache, model set, API URLs) in one UI, then keeps that same
dialog up with the live log while Arch and tabby-stack install.
install.sh is non-interactive from here so it does not open a second
dialog. The NVIDIA driver loads on the first real boot; linger then
starts the API.

The kernel driver is nvidia-open (Arch dropped the nvidia package). That
covers Turing / RTX 20-series and newer. GTX 10xx and older need the AUR
580xx driver, which this installer does not install.
EOF
}

TSOS_LOG="${TSOS_LOG:-/tmp/tsos-installer.log}"
TSOS_WATCH_PID=""
TSOS_GAUGE_DIR=""
TSOS_SAVED_FD=""

log() {
  printf '==> %s\n' "$*" >>"$TSOS_LOG"
  if [[ -z "${TSOS_SAVED_FD:-}" ]]; then
    printf '==> %s\n' "$*"
  fi
}
warn() {
  printf 'warning: %s\n' "$*" >>"$TSOS_LOG"
  printf 'warning: %s\n' "$*" >&2
}
die() {
  if declare -F gauge_stop >/dev/null; then
    gauge_stop || true
  fi
  printf 'error: %s\n' "$*" >&2
  if [[ ! -t 2 ]] && have_console; then
    printf 'error: %s\n' "$*" >/dev/tty
  fi
  exit 1
}

# curl | bash puts the script on stdin. After bash has parsed this file,
# point stdin at the keyboard so child tools do not read the pipe.
# /dev/tty can exist as a node and still fail to open when there is no console.
have_console() {
  { : </dev/tty; } 2>/dev/null
}

attach_console() {
  if [[ -t 0 ]]; then
    return 0
  fi
  if have_console; then
    exec </dev/tty
  fi
}

need_tty() {
  have_console || die "No controlling terminal. curl | bash must run on the live ISO console or via ssh -t."
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

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
  [[ -n "$TUI" ]] && return 0
  ((DRY_RUN)) && return 0
  have_console || [[ -t 0 ]] || return 0
  log "Installing dialog (ncurses menus)"
  disable_live_mkinitcpio_hooks
  pacman -Sy --noconfirm --needed dialog || true
  tui_cmd
}

enable_tui_if_possible() {
  if [[ -n "$TUI" ]] && { [[ -t 0 && -t 1 ]] || have_console; }; then
    USE_TUI=1
  fi
}

restore_tty() {
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

# Work-phase UI uses the same foreground dialog as the questions.
# A background --gauge is put in state T (SIGTTOU / "suspended (tty output)")
# on this ISO, so it never paints and the shell is left showing stdout.
ensure_work_term() {
  set +m 2>/dev/null || true
  case "${TERM:-}" in
    "" | dumb | unknown) export TERM=linux ;;
  esac
  stty sane -tostop </dev/tty >/dev/null 2>&1 || true
}

tsos_log_snippet() {
  local n=8
  [[ -f "$TSOS_LOG" ]] || return 0
  tail -n 40 "$TSOS_LOG" 2>/dev/null \
    | tr '\r' '\n' \
    | sed -e 's/\x1B\[[0-9;?]*[a-zA-Z]//g' \
    | grep -v '^[[:space:]]*$' \
    | tail -n "$n" \
    | cut -c1-70 || true
}

paint_work_ui() {
  local body="$1"
  ((USE_TUI)) || return 0
  [[ "$TUI" == dialog ]] || return 0
  if [[ -n "${TSOS_SAVED_FD:-}" ]]; then
    dialog --backtitle "$BACKTITLE" --title "Installing  tsos ${SCRIPT_VERSION}" \
      --infobox "$body" 14 74 >/dev/tty || true
  else
    dialog --backtitle "$BACKTITLE" --title "Installing  tsos ${SCRIPT_VERSION}" \
      --infobox "$body" 14 74 || true
  fi
}

work_ui_body() {
  local pct heading snippet
  pct=0
  heading="Working..."
  [[ -f "${TSOS_GAUGE_DIR:-}/pct" ]] && pct=$(cat "$TSOS_GAUGE_DIR/pct" 2>/dev/null || true)
  [[ -f "${TSOS_GAUGE_DIR:-}/heading" ]] && heading=$(cat "$TSOS_GAUGE_DIR/heading" 2>/dev/null || true)
  [[ "$pct" =~ ^[0-9]+$ ]] || pct=0
  snippet=$(tsos_log_snippet)
  printf '[%s%%] %s\n\n%s\n' "$pct" "$heading" "$snippet"
}

watch_installer_ui() {
  set +e
  local stop="$1" last="" elapsed=0 body
  while [[ ! -f "$stop" ]]; do
    body=$(work_ui_body)
    if [[ "$body" == "$last" ]]; then
      elapsed=$((elapsed + 1))
      body="$body
(${elapsed}s)"
    else
      last=$body
      elapsed=0
    fi
    paint_work_ui "$body"
    sleep 0.5
  done
}

gauge_start() {
  ((USE_TUI)) || return 1
  [[ "$TUI" == dialog ]] || return 1
  have_console || [[ -t 1 ]] || return 1
  ensure_work_term
  touch "$TSOS_LOG"
  TSOS_GAUGE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/tsos-ui.XXXXXX")
  printf '%s\n' 0 >"$TSOS_GAUGE_DIR/pct"
  printf '%s\n' "Starting the install..." >"$TSOS_GAUGE_DIR/heading"
  paint_work_ui "[0%] Starting the install (tsos ${SCRIPT_VERSION})"
  exec 4>&1 5>&2
  TSOS_SAVED_FD=1
  exec >>"$TSOS_LOG" 2>&1
  watch_installer_ui "$TSOS_GAUGE_DIR/stop" &
  TSOS_WATCH_PID=$!
  return 0
}

gauge_update() {
  local pct="$1" msg="$2"
  if [[ -n "${TSOS_GAUGE_DIR:-}" ]]; then
    printf '%s\n' "$pct" >"$TSOS_GAUGE_DIR/pct"
    printf '%s\n' "$msg" >"$TSOS_GAUGE_DIR/heading"
  fi
  log "[${pct}%] $msg"
  paint_work_ui "$(work_ui_body)"
}

gauge_stop() {
  if [[ -n "${TSOS_GAUGE_DIR:-}" ]]; then
    touch "$TSOS_GAUGE_DIR/stop" 2>/dev/null || true
  fi
  if [[ -n "${TSOS_WATCH_PID:-}" ]]; then
    kill "$TSOS_WATCH_PID" 2>/dev/null || true
    wait "$TSOS_WATCH_PID" 2>/dev/null || true
    TSOS_WATCH_PID=""
  fi
  rm -rf "${TSOS_GAUGE_DIR:-}"
  TSOS_GAUGE_DIR=""
  if [[ -n "${TSOS_SAVED_FD:-}" ]]; then
    exec 1>&4 2>&5
    exec 4>&- 5>&-
    TSOS_SAVED_FD=""
    restore_tty
  fi
}

ui_cancel() {
  die "Installer cancelled."
}

# dialog --stdout needs /dev/tty. That fails in some chroots. UI stays on
# stdout; the typed value is read from stderr via a temp file.
dialog_read() {
  local tmp rc
  tmp=$(mktemp "${TMPDIR:-/tmp}/tsos-dialog.XXXXXX") || return 1
  set +e
  dialog --backtitle "$BACKTITLE" "$@" 2> "$tmp"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    rm -f "$tmp"
    return "$rc"
  fi
  cat "$tmp"
  rm -f "$tmp"
  return 0
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
    printf '\n=== %s ===\n%s\n\n' "$title" "$text" >/dev/tty
  fi
}

ui_input() {
  local title="$1"
  local text="$2"
  local default="$3"
  local out=""
  if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
    out="$(dialog_read --title "$title" --inputbox "$text" 18 74 "$default")" || ui_cancel
  elif [[ "$USE_TUI" -eq 1 && "$TUI" == whiptail ]]; then
    out="$(whiptail --backtitle "$BACKTITLE" --title "$title" --inputbox "$text" 18 74 "$default" 3>&1 1>&2 2>&3)" || ui_cancel
  else
    out=$(ask "$title" "$default")
  fi
  printf '%s' "$out"
}

ui_menu() {
  local title="$1"
  local text="$2"
  shift 2
  local out=""
  if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
    out="$(dialog_read --title "$title" --menu "$text" 20 74 8 "$@")" || ui_cancel
  elif [[ "$USE_TUI" -eq 1 && "$TUI" == whiptail ]]; then
    out="$(whiptail --backtitle "$BACKTITLE" --title "$title" --menu "$text" 20 74 8 "$@" 3>&1 1>&2 2>&3)" || ui_cancel
  else
    local i=1 tag
    local tags=()
    {
      printf '\n=== %s ===\n%s\n\n' "$title" "$text"
      while (($#)); do
        tag="$1"
        tags+=("$tag")
        printf "  %s) %s — %s\n" "$i" "$tag" "$2"
        shift 2
        i=$((i + 1))
      done
    } >/dev/tty
    local choice=""
    choice=$(read_tty "Choice [1]: ")
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
    printf '\n=== %s ===\n%s\n\n' "$title" "$text" >/dev/tty
    local ans=""
    ans=$(read_tty "Continue? [$yn]: ")
    ans="${ans:-$([[ "$default_yes" -eq 1 ]] && echo y || echo n)}"
    [[ "$ans" =~ ^[Yy] ]]
  fi
}

ui_password() {
  local title="$1"
  local text="$2"
  local out=""
  if [[ "$USE_TUI" -eq 1 && "$TUI" == dialog ]]; then
    out="$(dialog_read --title "$title" --insecure --passwordbox "$text" 12 74)" || ui_cancel
  elif [[ "$USE_TUI" -eq 1 && "$TUI" == whiptail ]]; then
    out="$(whiptail --backtitle "$BACKTITLE" --title "$title" --passwordbox "$text" 12 74 3>&1 1>&2 2>&3)" || ui_cancel
  else
    out=$(read_secret "$title: ")
  fi
  printf '%s' "$out"
}

ui_ask_until() {
  local title=$1
  local text=$2
  local default=$3
  local validator=$4
  local value
  while true; do
    value=$(ui_input "$title" "$text" "$default")
    if "$validator" "$value"; then
      printf '%s' "$value"
      return 0
    fi
    ui_msg "Invalid value" "Not accepted: ${value}"
  done
}

read_tty() {
  local prompt=$1
  local value=""
  need_tty
  # Always write the prompt to the console. read -p is silent when stdin is a pipe.
  printf '%s' "$prompt" >/dev/tty
  # Empty Enter is valid (optional fields, keep-default). read returns 1 on EOF.
  IFS= read -r value </dev/tty || true
  printf '%s' "$value"
}

read_secret() {
  local prompt=$1
  local value=""
  need_tty
  printf '%s' "$prompt" >/dev/tty
  IFS= read -r -s value </dev/tty || true
  printf '\n' >/dev/tty
  printf '%s' "$value"
}

# Prompt on the console. Empty reply keeps the default. Writes the value to stdout.
ask() {
  local prompt=$1
  local default=${2-}
  local reply=""
  if [[ -n "$default" ]]; then
    reply=$(read_tty "$prompt [$default]: ")
    printf '%s' "${reply:-$default}"
  else
    reply=$(read_tty "$prompt: ")
    printf '%s' "$reply"
  fi
  return 0
}

valid_hostname() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,62}$ ]]
}

valid_username() {
  [[ "$1" =~ ^[a-z_][a-z0-9_-]*$ && "$1" != "root" ]]
}

valid_omarchy_mode() {
  [[ "$1" == "now" || "$1" == "skip" ]]
}

valid_esp_size() {
  [[ "$1" =~ ^[0-9]+([KMGT]i?B?|[kmgt])?$ ]]
}

valid_yes_no() {
  [[ "$1" == "yes" || "$1" == "no" ]]
}

valid_models() {
  [[ "$1" == "core" || "$1" == "all" ]]
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535))
}

ask_until() {
  local prompt=$1
  local default=$2
  local validator=$3
  local value
  while true; do
    value=$(ask "$prompt" "$default")
    if "$validator" "$value"; then
      printf '%s' "$value"
      return 0
    fi
    printf 'invalid value: %s\n' "$value" >/dev/tty
  done
}

show_available_disks() {
  local name size model iso="" marked=0
  iso=$(live_iso_disk || true)
  printf 'Disks on this machine:\n' >/dev/tty
  printf '%s\n' "$(lsblk -d -o NAME,SIZE,TYPE,MODEL)" >/dev/tty
  printf '\n' >/dev/tty
  while read -r name; do
    size=$(lsblk -dn -o SIZE "/dev/$name" 2>/dev/null | tr -d ' ')
    model=$(lsblk -dn -o MODEL "/dev/$name" 2>/dev/null | sed 's/[[:space:]]*$//')
    if [[ -n "$iso" && "/dev/$name" == "$iso" ]]; then
      printf '  /dev/%s\t%s\t%s\t(live ISO — cannot install here)\n' "$name" "$size" "$model" >/dev/tty
    else
      printf '  /dev/%s\t%s\t%s\n' "$name" "$size" "$model" >/dev/tty
      marked=1
    fi
  done < <(physical_disk_names)
  if ((marked == 0)); then
    printf '\nNo installable disk. The live USB/ISO is excluded so it is not wiped.\n' >/dev/tty
    printf 'Add another disk, or boot the ISO from a USB/DVD that is not the target drive.\n' >/dev/tty
  fi
}

ask_install_disk() {
  local default="" iso=""
  iso=$(live_iso_disk || true)
  default=$(first_install_disk || true)
  if [[ -n "$DISK" && "$DISK" != "$iso" && -b "$DISK" ]]; then
    default=$DISK
  elif [[ -z "$default" && -b "$DEFAULT_DISK" && "$DEFAULT_DISK" != "$iso" ]]; then
    default=$DEFAULT_DISK
  fi
  if [[ -z "$default" ]]; then
    die "No installable disk found. Attach a second drive, then run the script again.
$(lsblk -d -o NAME,SIZE,TYPE,MODEL)"
  fi

  if ((USE_TUI)); then
    local args=() path size model
    while IFS=$'\t' read -r path size model; do
      [[ -n "$path" ]] || continue
      args+=("$path" "${size}  ${model}")
    done < <(list_install_disks)
    ((${#args[@]})) || die "No installable disk found."
    DISK=$(ui_menu "1 / 10  — Target disk" \
"This disk will be wiped. The live ISO / USB you booted from is hidden.

Choose the machine disk, not a second installer stick." \
      "${args[@]}")
    return 0
  fi

  local value
  show_available_disks
  printf '\n' >/dev/tty
  while true; do
    value=$(ask "Target disk (WILL BE WIPED)" "$default")
    if [[ ! -b "$value" ]]; then
      printf 'not a block device: %s (check the list above)\n' "$value" >/dev/tty
      continue
    fi
    if [[ -n "$iso" && "$value" == "$iso" ]]; then
      printf '%s is the live ISO. Choose a different disk.\n' "$value" >/dev/tty
      continue
    fi
    DISK=$value
    return 0
  done
}

# Asked when --config is not passed. Defaults come from the script
# (or from a flag / env var if you already set one).
prompt_settings() {
  if ((USE_TUI)); then
    prompt_settings_tui
  else
    prompt_settings_text
  fi
}

prompt_settings_text() {
  log "No config file given. Enter settings, or press Enter to keep the default."
  printf '\n' >/dev/tty
  show_available_disks
  printf '\n' >/dev/tty

  ask_install_disk
  TARGET_HOSTNAME=$(ask_until "Hostname" "$TARGET_HOSTNAME" valid_hostname)
  TARGET_USER=$(ask_until "Username" "$TARGET_USER" valid_username)
  TIMEZONE=$(ask "Timezone" "$TIMEZONE")
  if [[ ! -e "/usr/share/zoneinfo/$TIMEZONE" ]]; then
    warn "timezone not found at /usr/share/zoneinfo/$TIMEZONE — continuing anyway"
  fi
  LOCALE=$(ask "Locale" "$LOCALE")
  KEYMAP=$(ask "Console keymap" "$KEYMAP")
  ESP_SIZE=$(ask_until "EFI partition size" "$ESP_SIZE" valid_esp_size)

  local omarchy_answer
  omarchy_answer=$(ask_until "Install Omarchy desktop (requires LUKS) (yes / no)" "$(omarchy_yes_no)" valid_yes_no)
  if [[ "$omarchy_answer" == "yes" ]]; then
    OMARCHY_MODE=now
  else
    OMARCHY_MODE=skip
  fi
  if [[ "$OMARCHY_MODE" == "now" ]]; then
    ENCRYPT=1
    printf 'Omarchy selected — disk encryption is required and will be enabled.\n' >/dev/tty
    OMARCHY_USER_NAME=$(ask "Git name (optional, used by Omarchy)" "$OMARCHY_USER_NAME")
    OMARCHY_USER_EMAIL=$(ask "Git email (optional, used by Omarchy)" "$OMARCHY_USER_EMAIL")
  else
    local encrypt_answer
    encrypt_answer=$(ask_until "Encrypt the disk with LUKS (yes / no)" "$(encrypt_label)" valid_yes_no)
    if [[ "$encrypt_answer" == "yes" ]]; then
      ENCRYPT=1
    else
      ENCRYPT=0
    fi
  fi

  TABBY_CACHE=$(ask "Weights cache path (optional; asked now so a USB can be saved before wipe)" "$TABBY_CACHE")
  TABBY_MODELS=$(ask_until "Model set (core / all)" "${TABBY_MODELS:-core}" valid_models)
  TABBY_NETWORK_HOST=$(ask "TabbyAPI listen address" "${TABBY_NETWORK_HOST:-127.0.0.1}")
  TABBY_NETWORK_PORT=$(ask_until "TabbyAPI listen port" "${TABBY_NETWORK_PORT:-5000}" valid_port)
  COMFYUI_URL=$(ask "ComfyUI URL" "${COMFYUI_URL:-http://127.0.0.1:8188}")
  TABBY_PUBLIC_BASE=$(ask "Public URL (blank = local only)" "${TABBY_PUBLIC_BASE}")
  TABBY_SSH_REMOTE=$(ask "SSH tunnel target (blank = none)" "${TABBY_SSH_REMOTE}")
  if [[ -n "$TABBY_SSH_REMOTE" ]]; then
    TABBY_SSH_FORWARD=$(ask "SSH -R spec" \
      "${TABBY_SSH_FORWARD:-127.0.0.1:12345:127.0.0.1:${TABBY_NETWORK_PORT}}")
    TABBY_SSH_KEY=$(ask "SSH key path" \
      "${TABBY_SSH_KEY:-/home/${TARGET_USER}/.ssh/id_ed25519}")
  else
    TABBY_SSH_FORWARD=""
    TABBY_SSH_KEY=""
  fi
  printf '\n' >/dev/tty
}

prompt_settings_tui() {
  ui_msg "What this installer does" \
"Install Arch Linux from this live ISO, then tabby-stack (Python,
venvs, model weights) before you reboot.

The target disk is wiped. First boot starts the API (linger).
Omarchy is optional and requires LUKS.

Needed
  • Official Arch live ISO, root, internet, x86_64
  • NVIDIA GPU (Turing / RTX 20-series or newer)
  • Secure Boot off

Next screens ask for the disk, system name, Omarchy, cache,
model set, and API URLs. After you confirm the wipe, this
same dialog stays up and shows the install log (pacman, Python,
weight files) inside the box. install.sh does not open a second
dialog.

Esc cancels."

  ask_install_disk

  TARGET_HOSTNAME=$(ui_ask_until "2 / 10  — Hostname" \
"Name of the installed system (not the live ISO hostname).

Letters, digits, and hyphens. Example: tsos" \
    "$TARGET_HOSTNAME" valid_hostname)

  TARGET_USER=$(ui_ask_until "2 / 10  — Username" \
"Regular wheel user that runs tabby-stack.

Lowercase, not root. Example: tabby" \
    "$TARGET_USER" valid_username)

  TIMEZONE=$(ui_input "3 / 10  — Timezone" \
"Timezone from /usr/share/zoneinfo.

Examples: UTC  Australia/Sydney  America/New_York" \
    "$TIMEZONE")
  TIMEZONE="${TIMEZONE:-UTC}"
  if [[ ! -e "/usr/share/zoneinfo/$TIMEZONE" ]]; then
    ui_msg "Timezone not found" \
"No file at /usr/share/zoneinfo/${TIMEZONE}.
Continuing anyway — fix it after boot if the clock is wrong."
  fi

  LOCALE=$(ui_input "3 / 10  — Locale" \
"Locale name without a leading #.

Example: en_US.UTF-8" \
    "$LOCALE")
  LOCALE="${LOCALE:-en_US.UTF-8}"

  KEYMAP=$(ui_input "3 / 10  — Console keymap" \
"Keyboard map for the console (and LUKS prompt).

Example: us" \
    "$KEYMAP")
  KEYMAP="${KEYMAP:-us}"

  ESP_SIZE=$(ui_ask_until "3 / 10  — EFI partition size" \
"FAT32 /boot size. 2G is enough for the kernel and Limine.

Examples: 2G  512M" \
    "$ESP_SIZE" valid_esp_size)

  if ui_yesno "4 / 10  — Omarchy desktop" \
"Install the official Omarchy desktop in the chroot?

Yes requires LUKS on the root disk (encryption will be turned on).
No skips Omarchy; you can still encrypt on the next screen.

Default is no." \
    0; then
    OMARCHY_MODE=now
    ENCRYPT=1
    ui_msg "Encryption required" \
"Omarchy is selected, so the disk will be encrypted with LUKS."
    OMARCHY_USER_NAME=$(ui_input "4 / 10  — Git name" \
"Optional name passed to Omarchy as OMARCHY_USER_NAME.

Blank is fine." \
      "$OMARCHY_USER_NAME")
    OMARCHY_USER_EMAIL=$(ui_input "4 / 10  — Git email" \
"Optional email passed to Omarchy as OMARCHY_USER_EMAIL.

Blank is fine." \
      "$OMARCHY_USER_EMAIL")
  else
    OMARCHY_MODE=skip
    if ui_yesno "5 / 10  — Disk encryption" \
"Encrypt the root disk with LUKS?

Yes = unlock password at boot (recommended).
No = unencrypted btrfs.

Default follows the current setting ($(encrypt_label))." \
      "$([[ "$(encrypt_label)" == yes ]] && echo 1 || echo 0)"; then
      ENCRYPT=1
    else
      ENCRYPT=0
    fi
  fi

  local cache_choice
  cache_choice=$(ui_menu "6 / 10  — Weights cache" \
"If weights already live on a USB copy of tabby-stack or another
folder, they must be named now — the new root mounts at /mnt next.

Mount the USB first if you want that option (not under /mnt).

Leave the cache empty to download from Hugging Face." \
    none "Download from Hugging Face (no cache)" \
    usb "Use /run/media/usb/tabby-stack" \
    custom "Type another path")
  case "$cache_choice" in
    none) TABBY_CACHE="" ;;
    usb) TABBY_CACHE="/run/media/usb/tabby-stack" ;;
    custom)
      TABBY_CACHE=$(ui_input "Weights cache path" \
"Folder that contains tabbyAPI/models and ComfyUI/models.

Examples
  /run/media/usb/tabby-stack
  /tmp/tabby-weights

Blank = download from Hugging Face." \
        "$TABBY_CACHE")
      ;;
    *) TABBY_CACHE="$cache_choice" ;;
  esac

  prompt_tabby_settings_tui
}

prompt_tabby_settings_tui() {
  local default_set="${TABBY_MODELS:-core}"
  if [[ -n "$TABBY_CACHE" && -d "$TABBY_CACHE/tabbyAPI/models" ]]; then
    default_set="all"
  fi
  TABBY_MODELS=$(ui_menu "7 / 10  — Model set" \
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
    all "every switch-to profile (incl. 27B / 35B / Gemma)")
  TABBY_MODELS="${TABBY_MODELS:-$default_set}"
  if [[ "$TABBY_MODELS" == "all" ]]; then
    ui_msg "Gemma / Hugging Face" \
"The “all” set includes Gemma weights that Hugging Face may gate.

If a later download returns 401 or 403:
  huggingface-cli login
  or:  export HF_TOKEN=...
  then re-run this installer (finished files are skipped).

You do not need a token for qwen / Flux / Qwen-Image."
  fi

  TABBY_NETWORK_HOST=$(ui_input "8 / 10  — API listen address" \
"Address TabbyAPI binds on. Clients (and Cursor) use this host.

  127.0.0.1  — this machine only (usual)
  0.0.0.0    — other devices on the LAN can connect

Do not put a public hostname here." \
    "${TABBY_NETWORK_HOST:-127.0.0.1}")
  TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"

  TABBY_NETWORK_PORT=$(ui_ask_until "8 / 10  — API listen port" \
"TCP port for the API. Default 5000.

Health:  http://${TABBY_NETWORK_HOST}:PORT/health
Cursor:  http://${TABBY_NETWORK_HOST}:PORT/v1" \
    "${TABBY_NETWORK_PORT:-5000}" valid_port)

  COMFYUI_URL=$(ui_input "9 / 10  — ComfyUI URL" \
"HTTP URL for ComfyUI after “switch to comfy”.

Usual value:  http://127.0.0.1:8188
Change this only if ComfyUI will listen somewhere else." \
    "${COMFYUI_URL:-http://127.0.0.1:8188}")
  COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"

  TABBY_PUBLIC_BASE=$(ui_input "9 / 10  — Public URL" \
"Optional URL written into image links and the public gallery.

Examples
  https://api.example.com/v1
  https://chat.example.com/api/v1

Blank = local only (http://${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}/v1).
Leave blank if you do not have a reverse proxy or tunnel." \
    "${TABBY_PUBLIC_BASE}")

  TABBY_SSH_REMOTE=$(ui_input "10 / 10  — SSH tunnel" \
"Optional SSH target that forwards a remote port to TabbyAPI.

Example:  user@host.example

Blank = no tunnel (API stays on this machine).
If you set a host, the next screens ask for the forward spec and key." \
    "${TABBY_SSH_REMOTE}")
  if [[ -n "$TABBY_SSH_REMOTE" ]]; then
    TABBY_SSH_FORWARD=$(ui_input "10 / 10  — SSH forward" \
"ssh -R spec: remote listen → local TabbyAPI.

Default matches the listen port you chose (${TABBY_NETWORK_PORT})." \
      "${TABBY_SSH_FORWARD:-127.0.0.1:12345:127.0.0.1:${TABBY_NETWORK_PORT}}")
    TABBY_SSH_FORWARD="${TABBY_SSH_FORWARD:-127.0.0.1:12345:127.0.0.1:${TABBY_NETWORK_PORT}}"
    TABBY_SSH_KEY=$(ui_input "10 / 10  — SSH key" \
"Key file for ${TABBY_SSH_REMOTE}.

The installer copies that key from a weights cache if present,
otherwise it creates a new ed25519 key. Install the .pub on the
tunnel host. Use this path unless your key has another name." \
      "${TABBY_SSH_KEY:-/home/${TARGET_USER}/.ssh/id_ed25519}")
    TABBY_SSH_KEY="${TABBY_SSH_KEY:-/home/${TARGET_USER}/.ssh/id_ed25519}"
  else
    TABBY_SSH_FORWARD=""
    TABBY_SSH_KEY=""
  fi
}

encrypt_label() {
  if ((ENCRYPT)); then
    printf 'yes'
  else
    printf 'no'
  fi
}

omarchy_yes_no() {
  if [[ "$OMARCHY_MODE" == "now" ]]; then
    printf 'yes'
  else
    printf 'no'
  fi
}

# /dev/sda 1 -> /dev/sda1
# /dev/nvme0n1 1 -> /dev/nvme0n1p1
# /dev/mmcblk0 2 -> /dev/mmcblk0p2
# /dev/vda 1 -> /dev/vda1
part_dev() {
  local disk=$1
  local n=$2
  case "$disk" in
    *[0-9]) printf '%sp%s\n' "$disk" "$n" ;;
    *) printf '%s%s\n' "$disk" "$n" ;;
  esac
}

is_uefi() {
  [[ -d /sys/firmware/efi ]]
}

btrfs_opts() {
  local opts="noatime,compress=zstd:1,space_cache=v2"
  if [[ -b "$DISK" ]] && [[ "$(lsblk -dn -o ROTA "$DISK" 2>/dev/null || echo 1)" == "0" ]]; then
    opts+=",ssd,discard=async"
  fi
  printf '%s\n' "$opts"
}

live_iso_disk() {
  local src disk
  for src in /run/archiso/bootmnt /run/archiso/copytoram /iso; do
    if src=$(findmnt -n -o SOURCE "$src" 2>/dev/null); then
      disk=$(lsblk -no PKNAME "$src" 2>/dev/null | head -n1 || true)
      if [[ -z "$disk" && "$src" == /dev/* ]]; then
        disk=$(lsblk -no PKNAME "$src" 2>/dev/null | head -n1 || true)
      fi
      if [[ -n "$disk" ]]; then
        printf '/dev/%s\n' "$disk"
        return 0
      fi
    fi
  done
  return 1
}

# NAME and TYPE only — MODEL often contains spaces and breaks field splitting.
physical_disk_names() {
  local name type
  while read -r name type; do
    [[ "$type" == "disk" ]] || continue
    [[ "$name" == loop* ]] && continue
    printf '%s\n' "$name"
  done < <(lsblk -dn -o NAME,TYPE)
}

list_install_disks() {
  local iso name size model
  iso=$(live_iso_disk || true)
  while read -r name; do
    [[ -n "$name" ]] || continue
    if [[ -n "$iso" && "/dev/$name" == "$iso" ]]; then
      continue
    fi
    size=$(lsblk -dn -o SIZE "/dev/$name" 2>/dev/null | tr -d ' ')
    model=$(lsblk -dn -o MODEL "/dev/$name" 2>/dev/null | sed 's/[[:space:]]*$//')
    printf '/dev/%s\t%s\t%s\n' "$name" "$size" "$model"
  done < <(physical_disk_names)
}

first_install_disk() {
  local line
  line=$(list_install_disks | head -n1 || true)
  [[ -n "$line" ]] || return 1
  printf '%s\n' "${line%%$'\t'*}"
}

cpu_ucode_pkg() {
  if grep -q AuthenticAMD /proc/cpuinfo 2>/dev/null; then
    printf '%s\n' amd-ucode
  elif grep -q GenuineIntel /proc/cpuinfo 2>/dev/null; then
    printf '%s\n' intel-ucode
  fi
}

# Arch removed the proprietary `nvidia` package when the 590 driver dropped
# Pascal. Official repos now ship nvidia-open (Turing / RTX 20-series+).
# nvidia-open Provides: NVIDIA-MODULE and Conflicts: nvidia — it does not
# provide the name `nvidia`, so pacman -S nvidia is "target not found".
# An outdated live ISO database may not list nvidia-open until after -Sy.
pacman_pkg_available() {
  pacman -Si "$1" >/dev/null 2>&1
}

sync_live_pacman() {
  disable_live_mkinitcpio_hooks
  log "Refreshing package databases"
  pacman -Sy --noconfirm
}

nvidia_pkg() {
  if pacman_pkg_available nvidia-open; then
    printf '%s\n' nvidia-open
  elif pacman_pkg_available nvidia; then
    printf '%s\n' nvidia
  else
    return 1
  fi
}

self_test() {
  local failed=0
  check() {
    local got=$1 expected=$2 label=$3
    if [[ "$got" != "$expected" ]]; then
      printf 'FAIL %s: got %q expected %q\n' "$label" "$got" "$expected" >&2
      failed=1
    else
      printf 'ok   %s\n' "$label"
    fi
  }
  check "$(part_dev /dev/sda 1)" /dev/sda1 "sda p1"
  check "$(part_dev /dev/sda 2)" /dev/sda2 "sda p2"
  check "$(part_dev /dev/vda 1)" /dev/vda1 "vda p1"
  check "$(part_dev /dev/nvme0n1 1)" /dev/nvme0n1p1 "nvme p1"
  check "$(part_dev /dev/nvme0n1 2)" /dev/nvme0n1p2 "nvme p2"
  check "$(part_dev /dev/mmcblk0 1)" /dev/mmcblk0p1 "mmc p1"
  check "$(part_dev /dev/loop0 1)" /dev/loop0p1 "loop p1"

  DISK=/dev/sda
  BOOT_N=1
  DATA_N=2
  BIOS_N=""
  BIOS_PART="stale"
  setup_partitions
  check "$BOOT_PART" /dev/sda1 "uefi boot part"
  check "$DATA_PART" /dev/sda2 "uefi data part"
  check "${BIOS_PART}" "" "uefi has no bios part"

  BIOS_N=1
  BOOT_N=2
  DATA_N=3
  setup_partitions
  check "$BIOS_PART" /dev/sda1 "bios bios part"
  check "$BOOT_PART" /dev/sda2 "bios boot part"
  check "$DATA_PART" /dev/sda3 "bios data part"

  ENCRYPT=1
  check "$(encrypt_label)" yes "encrypt label yes"
  ENCRYPT=0
  check "$(encrypt_label)" no "encrypt label no"

  if valid_omarchy_mode now && valid_omarchy_mode skip && ! valid_omarchy_mode later; then
    printf 'ok   omarchy now/skip\n'
  else
    printf 'FAIL omarchy mode: now/skip only\n' >&2
    failed=1
  fi

  if ((failed)); then
    die "self-test failed"
  fi
  log "self-test passed"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --disk)
        DISK=${2:?--disk requires a path}
        shift 2
        ;;
      --hostname)
        TARGET_HOSTNAME=${2:?}
        shift 2
        ;;
      --user)
        TARGET_USER=${2:?}
        shift 2
        ;;
      --timezone)
        TIMEZONE=${2:?}
        shift 2
        ;;
      --locale)
        LOCALE=${2:?}
        shift 2
        ;;
      --keymap)
        KEYMAP=${2:?}
        shift 2
        ;;
      --esp-size)
        ESP_SIZE=${2:?}
        shift 2
        ;;
      --encrypt)
        ENCRYPT=1
        shift
        ;;
      --no-encrypt)
        ENCRYPT=0
        shift
        ;;
      --with-omarchy)
        OMARCHY_MODE=now
        shift
        ;;
      --skip-omarchy)
        OMARCHY_MODE=skip
        shift
        ;;
      --name)
        OMARCHY_USER_NAME=${2:?}
        shift 2
        ;;
      --email)
        OMARCHY_USER_EMAIL=${2:?}
        shift 2
        ;;
      --models)
        TABBY_MODELS=${2:?}
        shift 2
        ;;
      --tabby-host)
        TABBY_NETWORK_HOST=${2:?}
        shift 2
        ;;
      --tabby-port)
        TABBY_NETWORK_PORT=${2:?}
        shift 2
        ;;
      --tabby-cache)
        TABBY_CACHE=${2:?}
        shift 2
        ;;
      --tabby-repo)
        TABBY_REPO=${2:?}
        shift 2
        ;;
      --tabby-local-src)
        TABBY_LOCAL_SRC=${2:?}
        shift 2
        ;;
      --resume-tabby)
        RESUME_TABBY=1
        shift
        ;;
      --config)
        [[ -f "${2:?}" ]] || die "config file not found: $2"
        # shellcheck disable=SC1090
        source "$2"
        CONFIG_PROVIDED=1
        shift 2
        ;;
      --confirm-wipe)
        CONFIRM_WIPE=${2:?}
        shift 2
        ;;
      --password-env)
        shift
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --self-test)
        self_test
        exit 0
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
  done
}

normalize_encrypt() {
  case "${ENCRYPT}" in
    1 | yes | true | on) ENCRYPT=1 ;;
    0 | no | false | off) ENCRYPT=0 ;;
    *) die "invalid ENCRYPT: $ENCRYPT (use 1/0 or yes/no)" ;;
  esac
}

validate_names() {
  valid_username "$TARGET_USER" || die "invalid user name: $TARGET_USER"
  valid_hostname "$TARGET_HOSTNAME" || die "invalid hostname: $TARGET_HOSTNAME"
  valid_omarchy_mode "$OMARCHY_MODE" || die "invalid OMARCHY_MODE: $OMARCHY_MODE (now or skip)"
  valid_esp_size "$ESP_SIZE" || die "invalid EFI size: $ESP_SIZE"
  valid_models "$TABBY_MODELS" || die "invalid TABBY_MODELS: $TABBY_MODELS (core or all)"
  valid_port "$TABBY_NETWORK_PORT" || die "invalid TabbyAPI port: $TABBY_NETWORK_PORT"
  normalize_encrypt
  if [[ "$OMARCHY_MODE" == "now" && "$ENCRYPT" -eq 0 ]]; then
    die "Omarchy requires LUKS. Re-run with encryption, or skip Omarchy."
  fi
  if [[ -n "$TABBY_LOCAL_SRC" ]]; then
    [[ -f "$TABBY_LOCAL_SRC/install.sh" && -f "$TABBY_LOCAL_SRC/tabbyAPI/pyproject.toml" ]] || \
      die "TABBY_LOCAL_SRC is not a tabby-stack tree: $TABBY_LOCAL_SRC"
  fi
}

pick_disk_if_needed() {
  if [[ -n "$DISK" ]]; then
    return 0
  fi
  local disks=() line
  mapfile -t disks < <(list_install_disks)
  ((${#disks[@]})) || die "no candidate disks found"
  if ((${#disks[@]} == 1)) && [[ -n "${CONFIRM_WIPE:-}" ]]; then
    DISK=${disks[0]%%$'\t'*}
    return 0
  fi
  if ((USE_TUI)); then
    local args=() path size model
    for line in "${disks[@]}"; do
      path=${line%%$'\t'*}
      size=${line#*$'\t'}
      model=${size#*$'\t'}
      size=${size%%$'\t'*}
      args+=("$path" "${size}  ${model}")
    done
    DISK=$(ui_menu "Target disk" \
"This disk will be wiped. The live ISO device is hidden." \
      "${args[@]}")
    return 0
  fi
  printf 'Available disks (the live ISO device is hidden):\n' >/dev/tty
  local i=1
  for line in "${disks[@]}"; do
    printf '  %d) %s\n' "$i" "$line" >/dev/tty
    i=$((i + 1))
  done
  local choice
  choice=$(read_tty "Select disk number: ")
  [[ "$choice" =~ ^[0-9]+$ ]] || die "invalid selection"
  ((choice >= 1 && choice <= ${#disks[@]})) || die "invalid selection"
  DISK=${disks[$((choice - 1))]%%$'\t'*}
}

require_disk() {
  [[ -n "$DISK" ]] || die "no disk selected (pass --disk /dev/sda)"
  if ((DRY_RUN)); then
    return 0
  fi
  if [[ ! -b "$DISK" ]]; then
    die "$DISK is not a disk on this machine. Run the installer from the Arch live ISO (or pass --dry-run to preview)."
  fi
  local iso
  if iso=$(live_iso_disk); then
    if [[ "$DISK" == "$iso" ]]; then
      die "$DISK looks like the live ISO. Refusing to wipe the USB/DVD you booted from."
    fi
  fi
}

confirm_wipe() {
  log "THIS WILL ERASE EVERYTHING ON $DISK"
  lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT "$DISK" || true
  if [[ -n "$CONFIRM_WIPE" ]]; then
    [[ "$CONFIRM_WIPE" == "$DISK" ]] || die "--confirm-wipe must match --disk exactly (got $CONFIRM_WIPE)"
    return 0
  fi
  local answer
  if ((USE_TUI)); then
    ui_msg "Install plan" \
"$(print_plan)

$(lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT "$DISK" 2>/dev/null || true)

THIS ERASES EVERYTHING ON ${DISK}." \
      22 74
    answer=$(ui_input "Confirm wipe" \
"Type the disk path exactly to erase it:

    ${DISK}

Anything else aborts." \
      "")
  else
    printf '\n' >/dev/tty
    printf '%s\n' "Settings are done. The installer is waiting for a wipe confirmation." >/dev/tty
    printf '%s\n' "Type the disk path exactly, then press Enter:" >/dev/tty
    printf '    %s\n' "$DISK" >/dev/tty
    answer=$(read_tty "Confirm wipe: ")
  fi
  [[ "$answer" == "$DISK" ]] || die "aborted (typed '$answer', needed '$DISK')"
}

collect_passwords() {
  if [[ -n "$PASSWORD" ]]; then
    LUKS_PASSWORD=${LUKS_PASSWORD:-$PASSWORD}
    USER_PASSWORD=${USER_PASSWORD:-$PASSWORD}
    ROOT_PASSWORD=${ROOT_PASSWORD:-$PASSWORD}
  fi
  local need=0
  if [[ -z "$USER_PASSWORD" || -z "$ROOT_PASSWORD" ]]; then
    need=1
  fi
  if ((ENCRYPT)) && [[ -z "$LUKS_PASSWORD" ]]; then
    need=1
  fi
  if ((need)); then
    local pw_text
    if ((ENCRYPT)); then
      pw_text="One password is used for LUKS, your user, and root unless you set the split variables."
    else
      pw_text="One password is used for your user and root unless you set the split variables."
    fi
    log "$pw_text"
    local first second
    if ((USE_TUI)); then
      while true; do
        first=$(ui_password "Password" "$pw_text")
        second=$(ui_password "Confirm password" "Type the same password again.")
        if [[ -z "$first" ]]; then
          ui_msg "Password required" "The password cannot be empty."
          continue
        fi
        if [[ "$first" != "$second" ]]; then
          ui_msg "Passwords did not match" "Try again."
          continue
        fi
        break
      done
    else
      first=$(read_secret "Password: ")
      second=$(read_secret "Confirm password: ")
      [[ -n "$first" ]] || die "password cannot be empty"
      [[ "$first" == "$second" ]] || die "passwords did not match"
    fi
    PASSWORD=$first
    USER_PASSWORD=${USER_PASSWORD:-$PASSWORD}
    ROOT_PASSWORD=${ROOT_PASSWORD:-$PASSWORD}
    if ((ENCRYPT)); then
      LUKS_PASSWORD=${LUKS_PASSWORD:-$PASSWORD}
    fi
  fi
  if ((ENCRYPT == 0)); then
    LUKS_PASSWORD=""
  fi
}

have_network() {
  if command -v curl >/dev/null; then
    curl -fsSL --connect-timeout 5 --max-time 10 -o /dev/null https://geo.mirror.pkgbuild.com/ && return 0
    curl -fsSL --connect-timeout 5 --max-time 10 -o /dev/null https://archlinux.org/ && return 0
    return 1
  fi
  ping -c1 -W5 geo.mirror.pkgbuild.com >/dev/null 2>&1 || ping -c1 -W5 archlinux.org >/dev/null 2>&1
}

secure_boot_enabled() {
  command -v bootctl >/dev/null || return 1
  local status=""
  if command -v timeout >/dev/null; then
    status=$(timeout 3 bootctl status 2>/dev/null || true)
  else
    status=$(bootctl status 2>/dev/null || true)
  fi
  grep -q 'Secure Boot: enabled' <<<"$status"
}

# Cheap checks before the questionnaire so a missing ISO/network fails immediately.
early_preflight() {
  ((DRY_RUN)) && return 0
  log "Checking this is an Arch live ISO with network..."
  [[ $(id -u) -eq 0 ]] || die "run as root from the Arch live ISO"
  [[ $(uname -m) == x86_64 ]] || die "this installer requires x86_64"
  command -v pacstrap >/dev/null || die "pacstrap not found. Boot the official Arch Linux ISO, then run this script again."
  command -v sgdisk >/dev/null || die "sgdisk not found (install gptfdisk on the live ISO)"
  if ! have_network; then
    die "no network. On Wi-Fi run: iwctl station wlan0 connect 'SSID'"
  fi
  if secure_boot_enabled; then
    die "Secure Boot is enabled. Turn it off in firmware before installing (NVIDIA + Limine)."
  fi
}

preflight() {
  ((DRY_RUN)) && return 0
  command -v cryptsetup >/dev/null || {
    log "Installing disk tools on the live ISO"
    disable_live_mkinitcpio_hooks
    pacman -Sy --noconfirm --needed cryptsetup btrfs-progs gptfdisk parted dosfstools
  }
  if [[ -d /sys/firmware/efi ]]; then
    log "Firmware: UEFI"
  else
    log "Firmware: BIOS/legacy (Limine will be installed for BIOS + GPT)"
  fi
}

# Installing packages on the live ISO can trip broken mkinitcpio hooks.
# Neutralize only the live ISO hooks — never the installed system's.
disable_live_mkinitcpio_hooks() {
  local hook
  for hook in /usr/share/libalpm/hooks/*mkinitcpio*; do
    [[ -e "$hook" ]] || continue
    ln -sfn /dev/null "$hook"
  done
}

print_plan() {
  local root_line data_kind
  if ((ENCRYPT)); then
    data_kind="LUKS      btrfs"
    root_line="  mapper:        /dev/mapper/$CRYPT_NAME"
  else
    data_kind="btrfs"
    root_line="  root fs:       $DATA_PART (unencrypted)"
  fi
  cat <<EOF

Install plan
  disk:          $DISK
  efi:           $BOOT_PART
  data:          $DATA_PART
$root_line
  hostname:      $TARGET_HOSTNAME
  user:          $TARGET_USER
  timezone:      $TIMEZONE
  locale:        $LOCALE
  keymap:        $KEYMAP
  firmware:      $(is_uefi && echo UEFI || echo BIOS)
  encryption:    $(encrypt_label)
  omarchy:       $OMARCHY_MODE
  tabby models:  ${TABBY_MODELS:-core}
  tabby listen:  ${TABBY_NETWORK_HOST:-127.0.0.1}:${TABBY_NETWORK_PORT:-5000}
  tabby public:  ${TABBY_PUBLIC_BASE:-'(none — local only)'}
  tabby ssh:     ${TABBY_SSH_REMOTE:-'(none — no tunnel)'}
  tabby cache:   ${TABBY_CACHE:-'(none — Hugging Face)'}
  tabby repo:    $TABBY_REPO
  tabby overlay: ${TABBY_LOCAL_SRC:-'(script dir if it contains install.sh)'}
  nvidia:        nvidia-open (Turing / RTX 20-series+; Arch no longer ships nvidia)

Layout
EOF
  if [[ -n "${BIOS_PART:-}" ]]; then
    printf '  %s   BIOS boot (unformatted, 1M)\n' "$BIOS_PART"
  fi
  cat <<EOF
  ${BOOT_PART}   FAT32     /boot     Limine + kernel
  ${DATA_PART}  ${data_kind}     @ @home @log @pkg @snapshots

EOF
}

setup_partitions() {
  BOOT_PART=$(part_dev "$DISK" "$BOOT_N")
  DATA_PART=$(part_dev "$DISK" "$DATA_N")
  # Must not end with a failing `&&` — with set -e that exits the script
  # immediately after the settings prompts on UEFI (BIOS_N is empty).
  if [[ -n "${BIOS_N:-}" ]]; then
    BIOS_PART=$(part_dev "$DISK" "$BIOS_N")
  else
    BIOS_PART=""
  fi
}

assign_partition_numbers() {
  if is_uefi; then
    BOOT_N=1
    DATA_N=2
    BIOS_N=""
  else
    BIOS_N=1
    BOOT_N=2
    DATA_N=3
  fi
  setup_partitions
}

wipe_and_partition() {
  log "Unmounting stale targets"
  swapoff -a || true
  if mountpoint -q "$TARGET"; then
    umount -R "$TARGET" || true
  fi
  if [[ -e "/dev/mapper/$CRYPT_NAME" ]]; then
    cryptsetup close "$CRYPT_NAME" || true
  fi

  log "Wiping $DISK"
  wipefs -af "$DISK"
  sgdisk --zap-all "$DISK"
  sgdisk -og "$DISK"

  local data_type=8300
  local data_name=root
  if ((ENCRYPT)); then
    data_type=8309
    data_name=cryptroot
  fi

  if [[ -n "$BIOS_N" ]]; then
    log "Creating BIOS boot + EFI + root partitions"
    sgdisk -n "${BIOS_N}:0:+1M" -t "${BIOS_N}:ef02" -c "${BIOS_N}:BIOS" "$DISK"
    sgdisk -n "${BOOT_N}:0:+${ESP_SIZE}" -t "${BOOT_N}:ef00" -c "${BOOT_N}:EFI" "$DISK"
    sgdisk -n "${DATA_N}:0:0" -t "${DATA_N}:${data_type}" -c "${DATA_N}:${data_name}" "$DISK"
  else
    log "Creating EFI + root partitions"
    sgdisk -n "${BOOT_N}:0:+${ESP_SIZE}" -t "${BOOT_N}:ef00" -c "${BOOT_N}:EFI" "$DISK"
    sgdisk -n "${DATA_N}:0:0" -t "${DATA_N}:${data_type}" -c "${DATA_N}:${data_name}" "$DISK"
  fi

  sgdisk -p "$DISK"
  partprobe "$DISK"
  udevadm settle || true
  sleep 2
  setup_partitions
  [[ -b "$BOOT_PART" ]] || die "EFI partition missing: $BOOT_PART"
  [[ -b "$DATA_PART" ]] || die "Root partition missing: $DATA_PART"
}

setup_storage() {
  log "Formatting EFI $BOOT_PART"
  mkfs.fat -F32 -n EFI "$BOOT_PART"

  local mapper
  if ((ENCRYPT)); then
    log "Creating LUKS on $DATA_PART"
    wipefs -af "$DATA_PART" || true
    printf '%s' "$LUKS_PASSWORD" | cryptsetup luksFormat --batch-mode --type luks2 --iter-time 2000 --key-file=- "$DATA_PART"
    printf '%s' "$LUKS_PASSWORD" | cryptsetup open --key-file=- "$DATA_PART" "$CRYPT_NAME"
    mapper="/dev/mapper/$CRYPT_NAME"
  else
    log "Formatting btrfs on $DATA_PART (no LUKS)"
    wipefs -af "$DATA_PART" || true
    mapper="$DATA_PART"
  fi

  log "Creating btrfs on $mapper"
  mkfs.btrfs -f -L tsos "$mapper"
  mount "$mapper" "$TARGET"
  btrfs subvolume create "$TARGET/@"
  btrfs subvolume create "$TARGET/@home"
  btrfs subvolume create "$TARGET/@log"
  btrfs subvolume create "$TARGET/@pkg"
  btrfs subvolume create "$TARGET/@snapshots"
  umount "$TARGET"

  local opts
  opts=$(btrfs_opts)
  log "Mounting subvolumes ($opts)"
  mount -o "${opts},subvol=@" "$mapper" "$TARGET"
  mkdir -p "$TARGET"/{boot,home,var/log,var/cache/pacman/pkg,.snapshots}
  mount -o "${opts},subvol=@home" "$mapper" "$TARGET/home"
  mount -o "${opts},subvol=@log" "$mapper" "$TARGET/var/log"
  mount -o "${opts},subvol=@pkg" "$mapper" "$TARGET/var/cache/pacman/pkg"
  mount -o "${opts},subvol=@snapshots" "$mapper" "$TARGET/.snapshots"
  mount "$BOOT_PART" "$TARGET/boot"
}

install_base() {
  sync_live_pacman

  local ucode nvidia
  ucode=$(cpu_ucode_pkg || true)
  nvidia=$(nvidia_pkg) || die "NVIDIA kernel package not in the repos (tried nvidia-open, then nvidia). Enable the extra repository and check that pacman -Sy succeeded."
  log "NVIDIA kernel package: $nvidia"

  local packages=(
    base base-devel linux linux-firmware linux-headers
    btrfs-progs cryptsetup
    networkmanager iwd wireless-regdb
    sudo git curl wget
    limine
    vim nano man-db
    pipewire pipewire-pulse pipewire-alsa wireplumber
    nvidia-utils
    docker
  )
  [[ -n "$ucode" ]] && packages+=("$ucode")
  packages+=("$nvidia")
  if is_uefi; then
    packages+=(efibootmgr)
  fi

  log "Installing Arch packages"
  pacstrap -K "$TARGET" "${packages[@]}"
  genfstab -U "$TARGET" >>"$TARGET/etc/fstab"
}

write_chroot_files() {
  local luks_uuid="" root_uuid=""
  if ((ENCRYPT)); then
    luks_uuid=$(blkid -s UUID -o value "$DATA_PART")
    [[ -n "$luks_uuid" ]] || die "could not read LUKS UUID from $DATA_PART"
    root_uuid=""
  else
    root_uuid=$(blkid -s UUID -o value "$DATA_PART")
    [[ -n "$root_uuid" ]] || die "could not read filesystem UUID from $DATA_PART"
  fi

  install -d "$TARGET/root"

  {
    printf 'TARGET_HOSTNAME=%q\n' "$TARGET_HOSTNAME"
    printf 'TARGET_USER=%q\n' "$TARGET_USER"
    printf 'TIMEZONE=%q\n' "$TIMEZONE"
    printf 'LOCALE=%q\n' "$LOCALE"
    printf 'KEYMAP=%q\n' "$KEYMAP"
    printf 'DISK=%q\n' "$DISK"
    printf 'BOOT_N=%q\n' "$BOOT_N"
    printf 'CRYPT_NAME=%q\n' "$CRYPT_NAME"
    printf 'ENCRYPT=%q\n' "$ENCRYPT"
    printf 'LUKS_UUID=%q\n' "$luks_uuid"
    printf 'ROOT_UUID=%q\n' "$root_uuid"
    printf 'UEFI=%q\n' "$(is_uefi && echo 1 || echo 0)"
    printf 'USER_PASSWORD=%q\n' "$USER_PASSWORD"
    printf 'ROOT_PASSWORD=%q\n' "$ROOT_PASSWORD"
    printf 'OMARCHY_MODE=%q\n' "$OMARCHY_MODE"
    printf 'OMARCHY_USER_NAME=%q\n' "$OMARCHY_USER_NAME"
    printf 'OMARCHY_USER_EMAIL=%q\n' "$OMARCHY_USER_EMAIL"
  } >"$TARGET/root/install-vars.sh"

  cat >"$TARGET/root/configure-arch.sh" <<'CHROOT'
#!/usr/bin/env bash
set -euo pipefail
source /root/install-vars.sh

echo "$TARGET_HOSTNAME" >/etc/hostname
cat >/etc/hosts <<EOF
127.0.0.1   localhost
::1         localhost
127.0.1.1   ${TARGET_HOSTNAME}.localdomain ${TARGET_HOSTNAME}
EOF

ln -sf "/usr/share/zoneinfo/${TIMEZONE}" /etc/localtime
hwclock --systohc

sed -i "s/^#${LOCALE}/${LOCALE}/" /etc/locale.gen
sed -i 's/^#en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen
locale-gen
printf 'LANG=%s\n' "$LOCALE" >/etc/locale.conf
printf 'KEYMAP=%s\n' "$KEYMAP" >/etc/vconsole.conf

echo "root:${ROOT_PASSWORD}" | chpasswd
extra_groups=wheel
if getent group docker >/dev/null 2>&1; then
  extra_groups+=,docker
fi
if ! id -u "$TARGET_USER" >/dev/null 2>&1; then
  useradd -m -G "$extra_groups" -s /bin/bash "$TARGET_USER"
else
  usermod -aG "$extra_groups" "$TARGET_USER"
fi
echo "${TARGET_USER}:${USER_PASSWORD}" | chpasswd

install -d -m 0750 /etc/sudoers.d
# Named 10-wheel so it sorts before the chroot NOPASSWD drop-in.
# A file named "wheel" sorts last and cancels NOPASSWD (sudo last-match wins).
printf '%s\n' '%wheel ALL=(ALL:ALL) ALL' >/etc/sudoers.d/10-wheel
chmod 0440 /etc/sudoers.d/10-wheel
# Passwordless sudo only while tabby-stack install.sh runs in the ISO chroot.
printf 'Defaults:%s !use_pty,!requiretty,!pam_session\n' "$TARGET_USER" >/etc/sudoers.d/zz-tsos-firstboot
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$TARGET_USER" >>/etc/sudoers.d/zz-tsos-firstboot
chmod 0440 /etc/sudoers.d/zz-tsos-firstboot
if [[ "$OMARCHY_MODE" != "skip" ]]; then
  printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$TARGET_USER" >/etc/sudoers.d/99-omarchy-installer
  chmod 0440 /etc/sudoers.d/99-omarchy-installer
fi

systemctl enable NetworkManager
systemctl enable NetworkManager-wait-online.service || true
systemctl enable docker.service || true
install -d -m 0755 /var/lib/systemd/linger
touch "/var/lib/systemd/linger/${TARGET_USER}"
loginctl enable-linger "$TARGET_USER" || true

if [[ "$ENCRYPT" == "1" ]]; then
  if grep -q '^HOOKS=' /etc/mkinitcpio.conf; then
    sed -i 's/^HOOKS=.*/HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block encrypt filesystems fsck)/' /etc/mkinitcpio.conf
  else
    printf '%s\n' 'HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block encrypt filesystems fsck)' >>/etc/mkinitcpio.conf
  fi
else
  if grep -q '^HOOKS=' /etc/mkinitcpio.conf; then
    sed -i 's/^HOOKS=.*/HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)/' /etc/mkinitcpio.conf
  else
    printf '%s\n' 'HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)' >>/etc/mkinitcpio.conf
  fi
fi
if grep -q '^MODULES=' /etc/mkinitcpio.conf; then
  sed -i 's/^MODULES=.*/MODULES=(btrfs)/' /etc/mkinitcpio.conf
else
  printf '%s\n' 'MODULES=(btrfs)' >>/etc/mkinitcpio.conf
fi
mkinitcpio -P

if [[ "$ENCRYPT" == "1" ]]; then
  CMDLINE="cryptdevice=UUID=${LUKS_UUID}:${CRYPT_NAME} root=/dev/mapper/${CRYPT_NAME} rw rootfstype=btrfs rootflags=subvol=@"
else
  CMDLINE="root=UUID=${ROOT_UUID} rw rootfstype=btrfs rootflags=subvol=@"
fi

write_limine_conf() {
  local dest=$1
  install -d "$(dirname "$dest")"
  cat >"$dest" <<EOF
timeout: 5

/Arch Linux
    protocol: linux
    path: boot():/vmlinuz-linux
    cmdline: ${CMDLINE}
    module_path: boot():/initramfs-linux.img

/Arch Linux (fallback)
    protocol: linux
    path: boot():/vmlinuz-linux
    cmdline: ${CMDLINE}
    module_path: boot():/initramfs-linux-fallback.img
EOF
}

install -d /boot/EFI/arch-limine /boot/EFI/BOOT /boot/limine /etc/pacman.d/hooks

if [[ "$UEFI" == "1" ]]; then
  cp /usr/share/limine/BOOTX64.EFI /boot/EFI/arch-limine/BOOTX64.EFI
  cp /usr/share/limine/BOOTX64.EFI /boot/EFI/BOOT/BOOTX64.EFI
  if [[ -f /usr/share/limine/BOOTIA32.EFI ]]; then
    cp /usr/share/limine/BOOTIA32.EFI /boot/EFI/arch-limine/BOOTIA32.EFI
    cp /usr/share/limine/BOOTIA32.EFI /boot/EFI/BOOT/BOOTIA32.EFI
  fi
  write_limine_conf /boot/EFI/arch-limine/limine.conf
  write_limine_conf /boot/EFI/BOOT/limine.conf
  write_limine_conf /boot/limine.conf

  if command -v efibootmgr >/dev/null; then
    efibootmgr --create \
      --disk "$DISK" \
      --part "$BOOT_N" \
      --label "Arch Linux Limine Bootloader" \
      --loader '\EFI\arch-limine\BOOTX64.EFI' \
      --unicode || true
  fi

  cat >/etc/pacman.d/hooks/99-limine.hook <<'HOOK'
[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = limine

[Action]
Description = Deploying Limine after upgrade...
When = PostTransaction
Exec = /bin/sh -c "/usr/bin/cp /usr/share/limine/BOOTX64.EFI /boot/EFI/arch-limine/ && /usr/bin/cp /usr/share/limine/BOOTX64.EFI /boot/EFI/BOOT/"
HOOK
else
  cp /usr/share/limine/limine-bios.sys /boot/limine/limine-bios.sys
  limine bios-install "$DISK"
  write_limine_conf /boot/limine/limine.conf
  write_limine_conf /boot/limine.conf

  cat >/etc/pacman.d/hooks/99-limine.hook <<HOOK
[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = limine

[Action]
Description = Deploying Limine after upgrade...
When = PostTransaction
Exec = /bin/sh -c "/usr/bin/limine bios-install ${DISK} && /usr/bin/cp /usr/share/limine/limine-bios.sys /boot/limine/"
HOOK
fi

install -d -m 0755 /usr/local/bin
cat >/usr/local/bin/install-omarchy <<'HELPER'
#!/usr/bin/env bash
set -euo pipefail
if ((EUID == 0)); then
  echo "Run this as your regular user, not root:" >&2
  echo "  install-omarchy" >&2
  exit 1
fi
export OMARCHY_ONLINE_INSTALL=true
if [[ -n "${OMARCHY_USER_NAME:-}" ]]; then
  export OMARCHY_USER_NAME
fi
if [[ -n "${OMARCHY_USER_EMAIL:-}" ]]; then
  export OMARCHY_USER_EMAIL
fi
echo "Starting official Omarchy installer..."
exec bash -c 'curl -fsSL https://omarchy.org/install | bash'
HELPER
chmod 0755 /usr/local/bin/install-omarchy

if [[ -n "$OMARCHY_USER_NAME" || -n "$OMARCHY_USER_EMAIL" ]]; then
  install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 0755 "/home/${TARGET_USER}"
  {
    if [[ -n "$OMARCHY_USER_NAME" ]]; then
      printf 'export OMARCHY_USER_NAME=%q\n' "$OMARCHY_USER_NAME"
    fi
    if [[ -n "$OMARCHY_USER_EMAIL" ]]; then
      printf 'export OMARCHY_USER_EMAIL=%q\n' "$OMARCHY_USER_EMAIL"
    fi
  } >"/home/${TARGET_USER}/.omarchy-identity"
  chown "${TARGET_USER}:${TARGET_USER}" "/home/${TARGET_USER}/.omarchy-identity"
  chmod 0600 "/home/${TARGET_USER}/.omarchy-identity"
  touch "/home/${TARGET_USER}/.bash_profile"
  if ! grep -q omarchy-identity "/home/${TARGET_USER}/.bash_profile"; then
    printf '\n[[ -f ~/.omarchy-identity ]] && source ~/.omarchy-identity\n' >>"/home/${TARGET_USER}/.bash_profile"
  fi
  chown "${TARGET_USER}:${TARGET_USER}" "/home/${TARGET_USER}/.bash_profile"
fi

# Drop secrets from the chroot copy of the vars file.
sed -i '/_PASSWORD=/d' /root/install-vars.sh
CHROOT
  chmod 0755 "$TARGET/root/configure-arch.sh"
}

write_tabby_bootstrap() {
  local stack_home="/home/${TARGET_USER}/tabby-stack"
  local conf_dir="$TARGET/etc/tsos"
  install -d -m 0755 "$conf_dir" "$TARGET/usr/local/bin" "$TARGET/etc/profile.d" \
    "$TARGET/var/lib/tsos" "$TARGET/etc/systemd/system"

  {
    printf 'TARGET_HOSTNAME=%q\n' "$TARGET_HOSTNAME"
    printf 'TARGET_USER=%q\n' "$TARGET_USER"
    printf 'ENCRYPT=%q\n' "$ENCRYPT"
    printf 'OMARCHY_MODE=%q\n' "$OMARCHY_MODE"
    printf 'TABBY_REPO=%q\n' "$TABBY_REPO"
    printf 'TABBY_MODELS=%q\n' "$TABBY_MODELS"
    printf 'TABBY_NETWORK_HOST=%q\n' "$TABBY_NETWORK_HOST"
    printf 'TABBY_NETWORK_PORT=%q\n' "$TABBY_NETWORK_PORT"
    printf 'TABBY_CACHE=%q\n' "$TABBY_CACHE"
    printf 'TABBY_PUBLIC_BASE=%q\n' "$TABBY_PUBLIC_BASE"
    printf 'TABBY_SSH_REMOTE=%q\n' "$TABBY_SSH_REMOTE"
    printf 'TABBY_SSH_FORWARD=%q\n' "$TABBY_SSH_FORWARD"
    printf 'TABBY_SSH_KEY=%q\n' "$TABBY_SSH_KEY"
    printf 'COMFYUI_URL=%q\n' "$COMFYUI_URL"
    printf 'TABBY_INSTALL_ROOT=%q\n' "$stack_home"
  } >"$conf_dir/install.conf"
  chmod 0644 "$conf_dir/install.conf"
  if [[ -n "${HF_TOKEN:-}" ]]; then
    printf 'HF_TOKEN=%q\n' "$HF_TOKEN" >"$conf_dir/secrets.env"
    chmod 0600 "$conf_dir/secrets.env"
  fi

  cat >"$TARGET/etc/motd" <<EOF

tabby-stack OS — log in as ${TARGET_USER} for API URLs and install status.

EOF

  cat >"$TARGET/usr/local/bin/tsos-motd" <<'MOTD'
#!/usr/bin/env bash
# Printed on interactive login. Safe to run any time.
set -euo pipefail

CONF=/etc/tsos/install.conf
if [[ -f "$CONF" ]]; then
  # shellcheck disable=SC1090
  source "$CONF"
fi

TARGET_USER="${TARGET_USER:-$USER}"
TABBY_INSTALL_ROOT="${TABBY_INSTALL_ROOT:-$HOME/tabby-stack}"
TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"
TABBY_NETWORK_PORT="${TABBY_NETWORK_PORT:-5000}"
ENCRYPT="${ENCRYPT:-1}"
OMARCHY_MODE="${OMARCHY_MODE:-skip}"
TABBY_MODELS="${TABBY_MODELS:-core}"
TABBY_PUBLIC_BASE="${TABBY_PUBLIC_BASE:-}"

STATUS_FILE="/home/${TARGET_USER}/.config/tabby-stack/tsos-firstboot.status"
DONE_FILE=/var/lib/tsos/tabby-firstboot.done
RESUME_FILE="/home/${TARGET_USER}/.config/tabby-stack/install-resume.env"
LOG_FILE="${TABBY_INSTALL_ROOT}/tabby-install.log"
FIRSTBOOT_LOG=/var/log/tsos-firstboot.log

lan_ips() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{
      gsub(/\/.*/, "", $4)
      if ($4 != "") { if (n++) printf " "; printf "%s", $4 }
    }'
  fi
}

health_line() {
  local url="http://127.0.0.1:${TABBY_NETWORK_PORT}/health"
  local body
  body=$(curl -sf --connect-timeout 2 --max-time 3 "$url" 2>/dev/null || true)
  if [[ "$body" == *'"status":"healthy"'* || "$body" == *'"status": "healthy"'* ]]; then
    printf 'healthy'
  elif [[ -n "$body" ]]; then
    printf 'up (not healthy yet)'
  else
    printf 'not listening'
  fi
}

install_status() {
  if [[ -f "$DONE_FILE" ]]; then
    printf 'finished'
    return 0
  fi
  if [[ -f "$RESUME_FILE" ]]; then
    printf 'waiting for NVIDIA reboot resume'
    return 0
  fi
  if [[ -f "$STATUS_FILE" ]]; then
    tr -d '\n' <"$STATUS_FILE"
    return 0
  fi
  printf 'not finished on the live ISO'
}

enc_label() {
  if [[ "$ENCRYPT" == "1" || "$ENCRYPT" == "yes" ]]; then
    printf 'LUKS + btrfs'
  else
    printf 'btrfs (unencrypted)'
  fi
}

omarchy_label() {
  case "$OMARCHY_MODE" in
    now) printf 'installed during setup (or run: install-omarchy)' ;;
    *) printf 'not selected — optional later: install-omarchy' ;;
  esac
}

listen_urls() {
  local host="$TABBY_NETWORK_HOST"
  local port="$TABBY_NETWORK_PORT"
  if [[ "$host" == "0.0.0.0" || "$host" == "::" ]]; then
    local ips
    ips=$(lan_ips)
    if [[ -n "$ips" ]]; then
      printf 'http://%s:%s  (also LAN: %s)' "127.0.0.1" "$port" "$ips"
    else
      printf 'http://127.0.0.1:%s  (listening on all interfaces)' "$port"
    fi
  else
    printf 'http://%s:%s' "$host" "$port"
  fi
}

api_url=$(listen_urls)
if [[ -n "$TABBY_PUBLIC_BASE" ]]; then
  public_line="$TABBY_PUBLIC_BASE"
else
  public_line="(none — local / LAN only)"
fi

cat <<EOF

================================================================
  tabby-stack OS
================================================================

  Host:       $(hostname 2>/dev/null || echo unknown)
  User:       ${TARGET_USER}
  Disk:       $(enc_label)
  Desktop:    $(omarchy_label)
  Models:     ${TABBY_MODELS}

  Install:    ${TABBY_INSTALL_ROOT}
  API:        ${api_url}
  UI:         http://127.0.0.1:${TABBY_NETWORK_PORT}/v1/ui
  Health:     curl -sS http://127.0.0.1:${TABBY_NETWORK_PORT}/health
  Editor:     http://<this-host>:${TABBY_NETWORK_PORT}/v1
  Model name: gpt-4o   (leave it — compatibility label only)
  Public:     ${public_line}

  Sign in to the UI with this Linux account (${TARGET_USER}).

  Status:     $(install_status)
  API health: $(health_line)
  Unit:       systemctl --user status tabbyapi
  Logs:       journalctl --user -u tabbyapi -f
  Update:     bash ${TABBY_INSTALL_ROOT}/update.sh
  How-to:     ${TABBY_INSTALL_ROOT}/tabbyAPI/HOW-TO-ARCH.txt
  MOTD:       tsos-motd

EOF

if [[ "$ENCRYPT" == "1" || "$ENCRYPT" == "yes" ]]; then
  cat <<EOF
  Disk unlock: enter the LUKS password at the Limine/unlock prompt.

EOF
fi

if [[ ! -f "$DONE_FILE" ]]; then
  cat <<EOF
  tabby-stack did not finish on the live ISO. Re-run tsos-installer.sh
  from the Arch ISO — install.sh is not run after reboot.
  Log:    ${LOG_FILE}

EOF
fi

printf '%s\n' "================================================================"
printf '\n'
MOTD
  chmod 0755 "$TARGET/usr/local/bin/tsos-motd"

  cat >"$TARGET/etc/profile.d/tsos-motd.sh" <<'PROFILE'
# tabby-stack login banner
if [[ -t 1 && $- == *i* ]] && command -v tsos-motd >/dev/null 2>&1; then
  tsos-motd
fi
PROFILE
  chmod 0644 "$TARGET/etc/profile.d/tsos-motd.sh"

  log "Cloning tabby-stack for the chroot install"
  if ! arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- \
    git clone "$TABBY_REPO" "$stack_home"; then
    die "git clone failed. Check network, then re-run. Repo: $TABBY_REPO"
  fi
  overlay_local_tabby_sources "$TARGET$stack_home"
}

# curl | bash clones GitHub. A local tree (this script's directory, or
# TABBY_LOCAL_SRC) is copied over that clone so ISO testing picks up
# install.sh fixes that are not on origin yet.
overlay_local_tabby_sources() {
  local dest="$1"
  local src=""
  if [[ -n "$TABBY_LOCAL_SRC" ]]; then
    [[ -d "$TABBY_LOCAL_SRC" ]] || die "TABBY_LOCAL_SRC is not a directory: $TABBY_LOCAL_SRC"
    src="$(cd "$TABBY_LOCAL_SRC" && pwd)"
  else
    local script="${BASH_SOURCE[0]:-}"
    case "$script" in
      "" | /dev/fd/* | /proc/self/fd/* | -) return 0 ;;
    esac
    [[ "$script" == /* ]] || script="$PWD/$script"
    src="$(cd "$(dirname "$script")" && pwd)"
  fi
  [[ -f "$src/install.sh" && -f "$src/tabbyAPI/pyproject.toml" ]] || {
    [[ -n "$TABBY_LOCAL_SRC" ]] && die "TABBY_LOCAL_SRC is not a tabby-stack tree: $src"
    return 0
  }
  [[ "$src" == "$dest" ]] && return 0
  log "Overlaying local tabby-stack from $src"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude '.git/' \
      --exclude 'tabbyAPI/venv/' \
      --exclude 'tabbyAPI/models/' \
      --exclude 'ComfyUI/' \
      --exclude 'tabby-install.log' \
      --exclude '.tabby-update-backup/' \
      "$src/" "$dest/"
  else
    local name
    for name in install.sh update.sh uninstall.sh tsos-installer.sh AGENTS.md README.md; do
      [[ -e "$src/$name" ]] && cp -a "$src/$name" "$dest/$name"
    done
    mkdir -p "$dest/tabbyAPI"
    cp -a "$src/tabbyAPI/." "$dest/tabbyAPI/"
    rm -rf "$dest/tabbyAPI/venv" "$dest/tabbyAPI/models"
  fi
  chown_target_user_tree "/home/${TARGET_USER}/tabby-stack"
}

# Root writing into /home/USER leaves root-owned files. install.sh runs as
# TARGET_USER and dies on the first append (tabby-install.log).
chown_target_user_tree() {
  local rel="$1"
  arch-chroot "$TARGET" /usr/bin/chown -R "${TARGET_USER}:${TARGET_USER}" "$rel" || true
}

ensure_target_user_file() {
  local host_path="$1"
  local rel="${host_path#"$TARGET"}"
  [[ "$rel" == /* ]] || rel="/$rel"
  local rel_dir
  rel_dir=$(dirname "$rel")
  arch-chroot "$TARGET" /usr/bin/install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 0755 "$rel_dir"
  if [[ ! -e "$host_path" ]]; then
    arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- touch "$rel"
  fi
  arch-chroot "$TARGET" /usr/bin/chown "${TARGET_USER}:${TARGET_USER}" "$rel"
  chmod 0644 "$host_path" || true
}

# After a failed chroot install.sh, pull origin/main then overlay a local
# tree so fixes that are not on the ISO copy get used.
refresh_tabby_stack_in_target() {
  local stack_home="/home/${TARGET_USER}/tabby-stack"
  [[ -d "$TARGET$stack_home" ]] || die "missing $stack_home on the new system"
  if [[ -d "$TARGET$stack_home/.git" ]]; then
    log "Updating tabby-stack in the chroot from origin"
    arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- \
      git -C "$stack_home" fetch --prune origin || \
      warn "git fetch failed; using the tree already on disk"
    if ! arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- \
         git -C "$stack_home" merge --ff-only origin/main; then
      arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- \
        git -C "$stack_home" pull --ff-only || \
        warn "git pull failed; using the tree already on disk"
    fi
  fi
  overlay_local_tabby_sources "$TARGET$stack_home"
}

# If the weights cache is under $TARGET (often /mnt/usb), mounting the new
# root there would hide it. Bind it aside before wipe/mount.
preserve_tabby_cache() {
  [[ -n "$TABBY_CACHE" ]] || return 0
  if [[ ! -d "$TABBY_CACHE" ]]; then
    warn "TABBY_CACHE is not a directory: $TABBY_CACHE — ignoring"
    TABBY_CACHE=""
    return 0
  fi
  local cache_abs
  cache_abs=$(cd "$TABBY_CACHE" && pwd)
  if [[ "$cache_abs" == "$TARGET" || "$cache_abs" == "$TARGET"/* ]]; then
    log "Moving weights cache off $TARGET so the new root can mount there"
    mkdir -p "$CACHE_STAGING"
    mount --bind "$cache_abs" "$CACHE_STAGING"
    TABBY_CACHE="$CACHE_STAGING"
  fi
}

bind_tabby_cache_into_target() {
  TABBY_CACHE_CHROOT=""
  [[ -n "$TABBY_CACHE" && -d "$TABBY_CACHE" ]] || return 0
  local cache_abs
  cache_abs=$(cd "$TABBY_CACHE" && pwd)
  if [[ "$cache_abs" == "$TARGET" || "$cache_abs" == "$TARGET"/* ]]; then
    TABBY_CACHE_CHROOT="${cache_abs#"$TARGET"}"
    [[ -n "$TABBY_CACHE_CHROOT" ]] || TABBY_CACHE_CHROOT="/"
    return 0
  fi
  if mountpoint -q "$TARGET$CACHE_CHROOT_PATH" 2>/dev/null; then
    TABBY_CACHE_CHROOT="$CACHE_CHROOT_PATH"
    return 0
  fi
  log "Binding weights cache into the new system at $CACHE_CHROOT_PATH"
  mkdir -p "$TARGET$CACHE_CHROOT_PATH"
  mount --bind "$cache_abs" "$TARGET$CACHE_CHROOT_PATH"
  TABBY_CACHE_CHROOT="$CACHE_CHROOT_PATH"
}

run_tabby_install_chroot() {
  local stack_home="/home/${TARGET_USER}/tabby-stack"
  [[ -f "$TARGET$stack_home/install.sh" ]] || die "missing $stack_home/install.sh on the new system"

  bind_tabby_cache_into_target
  write_firstboot_sudoers "$TARGET"

  log "Installing tabby-stack in the new system (Python, venvs, model files)"
  log "This stays on the live ISO until it finishes. Full log: $stack_home/tabby-install.log"
  gauge_update 45 "Installing tabby-stack"

  local -a run_env=(
    HOME="/home/${TARGET_USER}"
    USER="$TARGET_USER"
    LOGNAME="$TARGET_USER"
    TERM="${TERM:-linux}"
    TABBY_SKIP_NVIDIA_REBOOT=1
    TABBY_INSTALL_ROOT="$stack_home"
    TABBY_CACHE="${TABBY_CACHE_CHROOT:-}"
    TABBY_NONINTERACTIVE=1
    TABBY_NESTED_UI=1
    TABBY_INSTALL_VERBOSE=1
    PYTHONUNBUFFERED=1
    TABBY_ISO_CHROOT=1
    TABBY_MODELS="${TABBY_MODELS:-core}"
    TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"
    TABBY_NETWORK_PORT="${TABBY_NETWORK_PORT:-5000}"
    TABBY_PUBLIC_BASE="${TABBY_PUBLIC_BASE:-}"
    TABBY_SSH_REMOTE="${TABBY_SSH_REMOTE:-}"
    TABBY_SSH_FORWARD="${TABBY_SSH_FORWARD:-}"
    TABBY_SSH_KEY="${TABBY_SSH_KEY:-}"
    COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
  )
  log "install.sh will use the settings from this UI (no second dialog)"
  if [[ -n "${TSOS_GAUGE_DIR:-}" ]]; then
    touch "$TSOS_GAUGE_DIR/nested"
  fi
  if [[ -n "${HF_TOKEN:-}" ]]; then
    run_env+=(HF_TOKEN="$HF_TOKEN" HUGGING_FACE_HUB_TOKEN="$HF_TOKEN")
  fi

  local status=0
  local tabby_log="$TARGET$stack_home/tabby-install.log"
  chown_target_user_tree "$stack_home"
  ensure_target_user_file "$tabby_log"
  {
    echo "launching install.sh $(date -Iseconds)"
    echo "nested=1 verbose=1 (output stays in the installer dialog)"
  } >>"$tabby_log"
  chown_target_user_tree "$stack_home/tabby-install.log"

  set +e
  if command -v stdbuf >/dev/null 2>&1; then
    arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- env "${run_env[@]}" \
      bash "$stack_home/install.sh" </dev/null 3>&- 2>&1 | stdbuf -oL tee -a "$tabby_log"
  else
    arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- env "${run_env[@]}" \
      bash "$stack_home/install.sh" </dev/null 3>&- 2>&1 | tee -a "$tabby_log"
  fi
  status=${PIPESTATUS[0]}
  set -e
  chown_target_user_tree "$stack_home/tabby-install.log"

  if ((status != 0)); then
    die "install.sh failed in the chroot (exit ${status}). Not rebooting.
Log: ${TARGET}${stack_home}/tabby-install.log
Do not run this installer again from scratch — that wipes the disk.
Fix the tree (git pull or --tabby-local-src), then resume:
  ${SCRIPT_NAME} --resume-tabby
or:
  arch-chroot ${TARGET} /usr/bin/runuser -u ${TARGET_USER} -- env \\
    HOME=/home/${TARGET_USER} USER=${TARGET_USER} LOGNAME=${TARGET_USER} TERM=linux \\
    TABBY_ISO_CHROOT=1 TABBY_SKIP_NVIDIA_REBOOT=1 \\
    TABBY_INSTALL_ROOT=${stack_home} \\
    bash ${stack_home}/install.sh"
  fi

  refresh_tsos_conf_from_tabby_env
  install -d -m 0755 "$TARGET/var/lib/tsos"
  touch "$TARGET/var/lib/tsos/tabby-firstboot.done"
  rm -f "$TARGET/etc/sudoers.d/zz-tsos-firstboot" "$TARGET/etc/sudoers.d/99-tsos-firstboot" || true
  log "tabby-stack installed. After reboot, linger starts the API."
}

# MOTD reads /etc/tsos/install.conf. After install.sh, tabby.env has the
# listen address and model set the user actually chose.
refresh_tsos_conf_from_tabby_env() {
  local conf="$TARGET/etc/tsos/install.conf"
  local envf="$TARGET/home/${TARGET_USER}/tabby-stack/tabbyAPI/deploy/arch/tabby.env"
  [[ -f "$envf" && -f "$conf" ]] || return 0
  local line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      TABBY_NETWORK_HOST=*|TABBY_NETWORK_PORT=*|TABBY_PUBLIC_BASE=*|COMFYUI_URL=*|TABBY_INSTALL_ROOT=*|TABBY_MODELS=*|TABBY_SSH_REMOTE=*|TABBY_SSH_FORWARD=*|TABBY_SSH_KEY=*)
        key="${line%%=*}"
        sed -i "/^${key}=/d" "$conf"
        printf '%s\n' "$line" >> "$conf"
        ;;
    esac
  done < "$envf"
}

# sudoers.d is included in lexical order; last matching rule wins.
# A drop-in named "wheel" sorts after 99-* and cancels NOPASSWD.
write_firstboot_sudoers() {
  local root=$1
  install -d -m 0750 "$root/etc/sudoers.d"
  if [[ -f "$root/etc/sudoers.d/wheel" ]]; then
    mv "$root/etc/sudoers.d/wheel" "$root/etc/sudoers.d/10-wheel"
  fi
  if [[ -f "$root/etc/sudoers" ]] && ! grep -qE '^[[:space:]]*[@#]includedir[[:space:]]+/etc/sudoers.d' "$root/etc/sudoers"; then
    printf '\n@includedir /etc/sudoers.d\n' >>"$root/etc/sudoers"
  fi
  {
    printf 'Defaults:%s !use_pty,!requiretty,!pam_session\n' "$TARGET_USER"
    printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$TARGET_USER"
  } >"$root/etc/sudoers.d/zz-tsos-firstboot"
  chmod 0440 "$root/etc/sudoers.d/zz-tsos-firstboot"
}

configure_chroot() {
  log "Configuring the installed system"
  arch-chroot "$TARGET" /bin/bash /root/configure-arch.sh
}

install_omarchy_chroot() {
  if [[ "$OMARCHY_MODE" != "now" ]]; then
    return 0
  fi

  log "Installing Omarchy as ${TARGET_USER} (not root)"
  log "This is the official installer. It can take a long time."
  log "When Omarchy says Reboot Now, that prompt is skipped — this script reboots the ISO at the end."

  # Omarchy's finished.sh blocks forever on: gum confirm "Reboot Now"
  # Even with OMARCHY_CHROOT_INSTALL=1 it still waits. PATH hits this first.
  cat >"$TARGET/usr/local/bin/gum" <<'GUM'
#!/usr/bin/env bash
if [[ "${1:-}" == "confirm" ]]; then
  case "$*" in
    *"Reboot Now"*) exit 0 ;;
  esac
fi
exec /usr/bin/gum "$@"
GUM
  chmod 0755 "$TARGET/usr/local/bin/gum"

  local runner="$TARGET/home/${TARGET_USER}/run-omarchy.sh"
  cat >"$runner" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export HOME="/home/${TARGET_USER}"
export USER="${TARGET_USER}"
export LOGNAME="${TARGET_USER}"
export OMARCHY_CHROOT_INSTALL=1
export OMARCHY_ONLINE_INSTALL=true
export PATH="/usr/local/sbin:/usr/local/bin:/usr/bin"
cd "\$HOME"
if [[ -f "\$HOME/.omarchy-identity" ]]; then
  # shellcheck disable=SC1091
  source "\$HOME/.omarchy-identity"
fi
curl -fsSL https://omarchy.org/install | bash
EOF
  chown --reference="$TARGET/home/${TARGET_USER}" "$runner"
  chmod 0755 "$runner"

  local status=0
  set +e
  arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- /bin/bash "/home/${TARGET_USER}/run-omarchy.sh"
  status=$?
  set -e
  rm -f "$runner" "$TARGET/usr/local/bin/gum"

  if ((status != 0)); then
    warn "Omarchy installer exited with status $status."
    warn "The Arch base is installed and should boot."
    warn "After you unlock the disk (if encrypted) and log in as ${TARGET_USER}, run: install-omarchy"
  else
    log "Omarchy installer finished"
  fi
  # Omarchy removes 99-omarchy-installer when it finishes. Restore NOPASSWD
  # only if the chroot install.sh has not finished yet.
  if [[ ! -f "$TARGET/var/lib/tsos/tabby-firstboot.done" ]]; then
    write_firstboot_sudoers "$TARGET"
  fi
}

cleanup() {
  log "Cleaning installer files from the target"
  rm -f "$TARGET/root/configure-arch.sh" "$TARGET/usr/local/bin/gum"
  if [[ -f "$TARGET/root/install-vars.sh" ]]; then
    sed -i '/_PASSWORD=/d' "$TARGET/root/install-vars.sh" || true
  fi
  log "Unmounting"
  sync || true
  if mountpoint -q "$TARGET$CACHE_CHROOT_PATH" 2>/dev/null; then
    umount "$TARGET$CACHE_CHROOT_PATH" 2>/dev/null || umount -l "$TARGET$CACHE_CHROOT_PATH" 2>/dev/null || true
  fi
  # Omarchy/chroot can leave processes on /mnt; a blocking umount looks hung.
  if command -v fuser >/dev/null 2>&1; then
    fuser -km "$TARGET" 2>/dev/null || true
    sleep 1
  fi
  if ! umount -R "$TARGET" 2>/dev/null; then
    umount -R -l "$TARGET" 2>/dev/null || true
  fi
  if ((ENCRYPT)) && [[ -e "/dev/mapper/$CRYPT_NAME" ]]; then
    cryptsetup close "$CRYPT_NAME" || true
  fi
  if mountpoint -q "$CACHE_STAGING" 2>/dev/null; then
    umount "$CACHE_STAGING" 2>/dev/null || umount -l "$CACHE_STAGING" 2>/dev/null || true
  fi
}

final_message() {
  if [[ -f "$TARGET/etc/tsos/install.conf" ]]; then
    # shellcheck disable=SC1090
    source "$TARGET/etc/tsos/install.conf"
  fi
  cat <<EOF

Arch base is installed on $DISK.

Next boot:
  1. Remove the live ISO
EOF
  if ((ENCRYPT)); then
    cat <<EOF
  2. Enter the LUKS password at the Limine/unlock prompt
  3. Log in as ${TARGET_USER}
EOF
  else
    cat <<EOF
  2. Log in as ${TARGET_USER}
EOF
  fi
  cat <<EOF

tabby-stack
  Installed in the chroot at /home/${TARGET_USER}/tabby-stack
  After reboot, linger starts the API. install.sh is not run again.
  Model set: ${TABBY_MODELS}
  API:       http://${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}
  UI:        http://127.0.0.1:${TABBY_NETWORK_PORT}/v1/ui
  Watch:     journalctl --user -u tabbyapi -f
  Banner:    tsos-motd   (also printed on login)

EOF
  case "$OMARCHY_MODE" in
    now)
      cat <<EOF
Omarchy was requested in the chroot. If it finished, you should get that
desktop after boot. If it did not, log in and run:

  install-omarchy

EOF
      ;;
    skip)
      cat <<EOF
Omarchy was skipped. To add it later:

  install-omarchy

EOF
      ;;
  esac
}

offer_reboot() {
  if ((USE_TUI)); then
    if ui_yesno "Reboot" \
"Install finished. Remove the live USB/ISO now.

Reboot into the new system?" 1; then
      log "Rebooting"
      reboot || systemctl reboot || true
    else
      log "Staying on the live ISO"
    fi
    return 0
  fi
  printf '\n' >/dev/tty
  printf '%s\n' "Install finished. Remove the live USB/ISO now." >/dev/tty
  printf '%s\n' "Press Enter to reboot into the new system (Ctrl+C stays on the ISO)." >/dev/tty
  if have_console; then
    read_tty "Reboot: " >/dev/null
  else
    log "No console; rebooting in 8 seconds"
    sleep 8
  fi
  log "Rebooting"
  reboot || systemctl reboot || true
}

load_existing_tsos_conf() {
  local conf="$TARGET/etc/tsos/install.conf"
  [[ -f "$conf" ]] || return 0
  # shellcheck disable=SC1090
  source "$conf"
  if [[ -f "$TARGET/etc/tsos/secrets.env" ]]; then
    # shellcheck disable=SC1090
    source "$TARGET/etc/tsos/secrets.env"
  fi
}

# Finish install.sh after a chroot failure. /mnt must still be the new system.
resume_tabby_install() {
  [[ -f "$TARGET/etc/arch-release" ]] || \
    die "$TARGET is not an Arch install. Leave the new system mounted at $TARGET (do not reboot off the ISO)."
  local cli_cache="$TABBY_CACHE"
  load_existing_tsos_conf
  if [[ -n "$cli_cache" && -d "$cli_cache" ]]; then
    TABBY_CACHE="$cli_cache"
  fi
  valid_username "$TARGET_USER" || die "invalid user name: $TARGET_USER"
  local stack_home="/home/${TARGET_USER}/tabby-stack"
  [[ -f "$TARGET$stack_home/install.sh" ]] || \
    die "missing $stack_home/install.sh under $TARGET"
  write_firstboot_sudoers "$TARGET"
  refresh_tabby_stack_in_target
  gauge_start || true
  gauge_update 40 "Resuming tabby-stack"
  run_tabby_install_chroot
  if [[ "$OMARCHY_MODE" == "now" ]]; then
    gauge_stop
  fi
  install_omarchy_chroot
  cleanup
  gauge_stop
  final_message
  offer_reboot
}

main() {
  parse_args "$@"
  attach_console
  early_preflight
  if ((RESUME_TABBY)); then
    log "Resuming tabby-stack in the already-mounted system at $TARGET (no disk wipe)"
    if ((DRY_RUN)); then
      log "dry-run: would resume install.sh at $TARGET"
      exit 0
    fi
    resume_tabby_install
    exit 0
  fi
  if ((CONFIG_PROVIDED == 0)) || [[ -z "$DISK" ]]; then
    ensure_dialog
    enable_tui_if_possible
  fi
  if ((CONFIG_PROVIDED)); then
    pick_disk_if_needed
  else
    prompt_settings
  fi
  validate_names
  require_disk
  assign_partition_numbers
  if ((USE_TUI == 0)) || ((DRY_RUN)); then
    print_plan
  fi
  if ((DRY_RUN)); then
    log "dry-run: no changes made"
    exit 0
  fi
  preflight
  confirm_wipe
  collect_passwords
  gauge_start || true
  log "Starting the install..."
  gauge_update 2 "Preparing disk"
  disable_live_mkinitcpio_hooks
  timedatectl set-ntp true || true
  preserve_tabby_cache
  gauge_update 8 "Wiping and partitioning"
  wipe_and_partition
  gauge_update 15 "Formatting and mounting"
  setup_storage
  gauge_update 22 "Installing Arch packages"
  install_base
  gauge_update 38 "Configuring the new system"
  write_chroot_files
  configure_chroot
  write_tabby_bootstrap
  run_tabby_install_chroot
  if [[ "$OMARCHY_MODE" == "now" ]]; then
    gauge_stop
  fi
  install_omarchy_chroot
  if [[ -n "${TSOS_SAVED_FD:-}" ]]; then
    gauge_update 98 "Cleaning up"
  fi
  cleanup
  gauge_stop
  final_message
  offer_reboot
}

main "$@"
