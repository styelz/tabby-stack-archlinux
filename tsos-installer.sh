#!/usr/bin/env bash
# tsos-installer.sh
#
# Install Arch Linux from the official live ISO, then set up tabby-stack so
# the API is installed and started on first boot (linger, no login needed).
#
# Run as root from the Arch Linux live ISO. The target disk is wiped.
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
SCRIPT_VERSION="1.0.1"

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
OMARCHY_MODE="${OMARCHY_MODE:-skip}" # now | later | skip
OMARCHY_USER_NAME="${OMARCHY_USER_NAME:-}"
OMARCHY_USER_EMAIL="${OMARCHY_USER_EMAIL:-}"
TABBY_REPO="${TABBY_REPO:-https://github.com/styelz/tabby-stack-archlinux.git}"
TABBY_MODELS="${TABBY_MODELS:-core}"
TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"
TABBY_NETWORK_PORT="${TABBY_NETWORK_PORT:-5000}"
TABBY_CACHE="${TABBY_CACHE:-}"
TABBY_PUBLIC_BASE="${TABBY_PUBLIC_BASE:-}"
COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
DISK="${DISK:-}"
CONFIRM_WIPE="${CONFIRM_WIPE:-}"
PASSWORD="${PASSWORD:-}"
LUKS_PASSWORD="${LUKS_PASSWORD:-}"
USER_PASSWORD="${USER_PASSWORD:-}"
ROOT_PASSWORD="${ROOT_PASSWORD:-}"
DRY_RUN=0
CONFIG_PROVIDED=0
DEFAULT_DISK=/dev/sda

TARGET="/mnt"
CRYPT_NAME="$MAPPER_NAME"

usage() {
  cat <<EOF
${SCRIPT_NAME} v${SCRIPT_VERSION}

Install Arch Linux (btrfs + Limine, optional LUKS) from the live ISO, then
install tabby-stack on first boot. Omarchy is optional.

USAGE
  ${SCRIPT_NAME} [options]
  curl -fsSL https://raw.githubusercontent.com/styelz/tabby-stack-archlinux/main/tsos-installer.sh | bash
  curl -fsSL https://raw.githubusercontent.com/styelz/tabby-stack-archlinux/main/tsos-installer.sh | bash -s -- [options]

With no --config file, the script asks for every setting before it runs.
Press Enter to keep the default.

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
  --with-omarchy           Run the official Omarchy installer in the chroot
  --skip-omarchy           Do not install Omarchy (default)
  --defer-omarchy          Install Arch only; leave install-omarchy for first login
  --name "FULL NAME"       Git name passed to Omarchy as OMARCHY_USER_NAME
  --email ADDR             Git email passed to Omarchy as OMARCHY_USER_EMAIL
  --models SET             tabby-stack model set: core or all (default: core)
  --tabby-host ADDR        TabbyAPI listen address (default: 127.0.0.1)
  --tabby-port N           TabbyAPI listen port (default: 5000)
  --tabby-cache PATH       Optional local weights cache (USB copy of tabby-stack)
  --tabby-repo URL         Git remote to clone (default: tabby-stack-archlinux)
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
  OMARCHY_USER_NAME, OMARCHY_USER_EMAIL, OMARCHY_MODE (now|later|skip)
  TABBY_REPO, TABBY_MODELS, TABBY_NETWORK_HOST, TABBY_NETWORK_PORT
  TABBY_CACHE, TABBY_PUBLIC_BASE, COMFYUI_URL, HF_TOKEN

One password is used for the user, root, and disk encryption (when enabled)
unless you set the split password variables.

The live ISO's HOSTNAME (usually archiso) is ignored on purpose.

tabby-stack cannot finish inside the live ISO (the NVIDIA driver needs a
real boot). This script clones the repo and enables a first-boot service.
After you remove the ISO and reboot, linger runs install.sh and starts the API.

The kernel driver is nvidia-open (Arch dropped the nvidia package). That
covers Turing / RTX 20-series and newer. GTX 10xx and older need the AUR
580xx driver, which this installer does not install.
EOF
}

log() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() {
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
  [[ "$1" == "now" || "$1" == "later" || "$1" == "skip" ]]
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

  local value
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

  local encrypt_answer
  encrypt_answer=$(ask_until "Encrypt the disk with LUKS (yes / no)" "$(encrypt_label)" valid_yes_no)
  if [[ "$encrypt_answer" == "yes" ]]; then
    ENCRYPT=1
  else
    ENCRYPT=0
  fi

  OMARCHY_MODE=$(ask_until "Install Omarchy desktop (now / later / skip)" "$OMARCHY_MODE" valid_omarchy_mode)
  if [[ "$OMARCHY_MODE" != "skip" ]]; then
    if ((ENCRYPT == 0)); then
      warn "Omarchy expects LUKS + Limine + btrfs. It may refuse without encryption."
    fi
    OMARCHY_USER_NAME=$(ask "Git name (optional, used by Omarchy)" "$OMARCHY_USER_NAME")
    OMARCHY_USER_EMAIL=$(ask "Git email (optional, used by Omarchy)" "$OMARCHY_USER_EMAIL")
  fi

  TABBY_MODELS=$(ask_until "tabby-stack model set (core / all)" "$TABBY_MODELS" valid_models)
  TABBY_NETWORK_HOST=$(ask "TabbyAPI listen address (127.0.0.1 = this machine, 0.0.0.0 = LAN)" "$TABBY_NETWORK_HOST")
  TABBY_NETWORK_PORT=$(ask_until "TabbyAPI listen port" "$TABBY_NETWORK_PORT" valid_port)
  TABBY_CACHE=$(ask "Weights cache path (optional)" "$TABBY_CACHE")
  TABBY_PUBLIC_BASE=$(ask "Public API base URL (optional)" "$TABBY_PUBLIC_BASE")
  printf '\n' >/dev/tty
}

encrypt_label() {
  if ((ENCRYPT)); then
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
      --defer-omarchy)
        OMARCHY_MODE=later
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
  valid_omarchy_mode "$OMARCHY_MODE" || die "invalid OMARCHY_MODE: $OMARCHY_MODE (now, later, or skip)"
  valid_esp_size "$ESP_SIZE" || die "invalid EFI size: $ESP_SIZE"
  valid_models "$TABBY_MODELS" || die "invalid TABBY_MODELS: $TABBY_MODELS (core or all)"
  valid_port "$TABBY_NETWORK_PORT" || die "invalid TabbyAPI port: $TABBY_NETWORK_PORT"
  normalize_encrypt
  if [[ "$OMARCHY_MODE" != "skip" && "$ENCRYPT" -eq 0 ]]; then
    warn "Omarchy expects LUKS. Continuing without encryption."
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
  printf '\n' >/dev/tty
  printf '%s\n' "Settings are done. The installer is waiting for a wipe confirmation." >/dev/tty
  printf '%s\n' "Type the disk path exactly, then press Enter:" >/dev/tty
  printf '    %s\n' "$DISK" >/dev/tty
  local answer
  answer=$(read_tty "Confirm wipe: ")
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
    if ((ENCRYPT)); then
      log "One password is used for LUKS, your user, and root unless you set the split variables."
    else
      log "One password is used for your user and root unless you set the split variables."
    fi
    local first second
    first=$(read_secret "Password: ")
    second=$(read_secret "Confirm password: ")
    [[ -n "$first" ]] || die "password cannot be empty"
    [[ "$first" == "$second" ]] || die "passwords did not match"
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
  tabby models:  $TABBY_MODELS
  tabby listen:  ${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}
  tabby cache:   ${TABBY_CACHE:-'(none — Hugging Face)'}
  tabby repo:    $TABBY_REPO
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
printf '%s\n' '%wheel ALL=(ALL:ALL) ALL' >/etc/sudoers.d/wheel
chmod 0440 /etc/sudoers.d/wheel
# Passwordless sudo only while the first-boot tabby-stack installer runs.
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$TARGET_USER" >/etc/sudoers.d/99-tsos-firstboot
chmod 0440 /etc/sudoers.d/99-tsos-firstboot
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
  install -d "/home/${TARGET_USER}"
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
  printf 'pending (first boot)'
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
    later) printf 'deferred — after login run: install-omarchy' ;;
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
  First boot: journalctl -u tsos-tabby-firstboot -f
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
  First boot is still installing tabby-stack (Python, venvs, model files).
  That can take a long time. Do not reboot unless the NVIDIA driver asks.
  Retry:  sudo systemctl start tsos-tabby-firstboot
  Log:    ${FIRSTBOOT_LOG}
          ${LOG_FILE}

EOF
fi

if [[ "$OMARCHY_MODE" == "later" ]]; then
  cat <<EOF
  Omarchy was not installed yet. After this account's first login:

    install-omarchy

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

  cat >"$TARGET/usr/local/bin/tsos-firstboot" <<'FIRSTBOOT'
#!/usr/bin/env bash
set -euo pipefail

CONF=/etc/tsos/install.conf
[[ -f "$CONF" ]] || {
  echo "missing $CONF" >&2
  exit 1
}
# shellcheck disable=SC1090
source "$CONF"
if [[ -f /etc/tsos/secrets.env ]]; then
  # shellcheck disable=SC1091
  source /etc/tsos/secrets.env
fi

STACK="${TABBY_INSTALL_ROOT:-/home/${TARGET_USER}/tabby-stack}"
STATUS_DIR="/home/${TARGET_USER}/.config/tabby-stack"
STATUS_FILE="${STATUS_DIR}/tsos-firstboot.status"
DONE_FILE=/var/lib/tsos/tabby-firstboot.done
RESUME_FILE="${STATUS_DIR}/install-resume.env"
LOG=/var/log/tsos-firstboot.log
REPO="${TABBY_REPO:-https://github.com/styelz/tabby-stack-archlinux.git}"

install -d -m 0755 /var/lib/tsos /var/log
install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 0755 "$STATUS_DIR" "$(dirname "$STACK")"

write_status() {
  printf '%s\n' "$1" >"$STATUS_FILE"
  chown "${TARGET_USER}:${TARGET_USER}" "$STATUS_FILE" || true
}

log() { printf '%s %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG"; }

if [[ -f "$DONE_FILE" ]]; then
  log "tabby-stack first-boot already finished"
  exit 0
fi

write_status "running"
log "Starting tabby-stack first-boot"

wait_network() {
  local i
  for i in $(seq 1 90); do
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL --connect-timeout 5 --max-time 10 -o /dev/null https://github.com/ && return 0
      curl -fsSL --connect-timeout 5 --max-time 10 -o /dev/null https://archlinux.org/ && return 0
    fi
    sleep 2
  done
  return 1
}

if ! wait_network; then
  write_status "failed"
  log "No network after waiting. Retry: systemctl start tsos-tabby-firstboot"
  exit 1
fi

loginctl enable-linger "$TARGET_USER" || true
uid=$(id -u "$TARGET_USER")
runtime="/run/user/${uid}"
for _ in $(seq 1 30); do
  [[ -d "$runtime" ]] && break
  sleep 1
done

if [[ ! -f "$STACK/install.sh" ]]; then
  log "Cloning $REPO into $STACK"
  rm -rf "$STACK"
  if ! runuser -u "$TARGET_USER" -- git clone "$REPO" "$STACK"; then
    write_status "failed"
    log "git clone failed"
    exit 1
  fi
fi

# install.sh may have scheduled an NVIDIA reboot and enabled its own
# resume unit. Only this service should continue, so sudoers cleanup runs.
if [[ -d "$runtime" ]]; then
  runuser -u "$TARGET_USER" -- env XDG_RUNTIME_DIR="$runtime" \
    systemctl --user disable --now tabby-install-resume.service >/dev/null 2>&1 || true
fi

export HOME="/home/${TARGET_USER}"
export USER="$TARGET_USER"
export LOGNAME="$TARGET_USER"
export XDG_RUNTIME_DIR="$runtime"
export TABBY_NONINTERACTIVE=1
export TABBY_INSTALL_ROOT="$STACK"
export TABBY_MODELS="${TABBY_MODELS:-core}"
export TABBY_NETWORK_HOST="${TABBY_NETWORK_HOST:-127.0.0.1}"
export TABBY_NETWORK_PORT="${TABBY_NETWORK_PORT:-5000}"
export TABBY_CACHE="${TABBY_CACHE:-}"
export TABBY_PUBLIC_BASE="${TABBY_PUBLIC_BASE:-}"
export COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
if [[ -n "${HF_TOKEN:-}" ]]; then
  export HF_TOKEN
  export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
fi

set +e
runuser -u "$TARGET_USER" -- env \
  HOME="$HOME" \
  USER="$USER" \
  LOGNAME="$LOGNAME" \
  XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
  TABBY_NONINTERACTIVE=1 \
  TABBY_INSTALL_ROOT="$TABBY_INSTALL_ROOT" \
  TABBY_MODELS="$TABBY_MODELS" \
  TABBY_NETWORK_HOST="$TABBY_NETWORK_HOST" \
  TABBY_NETWORK_PORT="$TABBY_NETWORK_PORT" \
  TABBY_CACHE="$TABBY_CACHE" \
  TABBY_PUBLIC_BASE="$TABBY_PUBLIC_BASE" \
  COMFYUI_URL="$COMFYUI_URL" \
  ${HF_TOKEN:+HF_TOKEN="$HF_TOKEN"} \
  ${HF_TOKEN:+HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"} \
  bash "$STACK/install.sh" >>"$LOG" 2>&1
status=$?
set -e

if [[ -f "$RESUME_FILE" ]]; then
  write_status "nvidia-reboot"
  log "NVIDIA driver needs a reboot. This service will continue after reboot."
  exit 0
fi

if ((status != 0)); then
  write_status "failed"
  log "install.sh exited $status. See $LOG and $STACK/tabby-install.log"
  exit "$status"
fi

write_status "finished"
touch "$DONE_FILE"
rm -f /etc/sudoers.d/99-tsos-firstboot || true
systemctl disable tsos-tabby-firstboot.service >/dev/null 2>&1 || true
log "tabby-stack first-boot finished"
FIRSTBOOT
  chmod 0755 "$TARGET/usr/local/bin/tsos-firstboot"

  cat >"$TARGET/etc/systemd/system/tsos-tabby-firstboot.service" <<EOF
[Unit]
Description=Install tabby-stack on first boot
After=network-online.target NetworkManager-wait-online.service systemd-user-sessions.service
Wants=network-online.target
ConditionPathExists=!/var/lib/tsos/tabby-firstboot.done

[Service]
Type=oneshot
ExecStart=/usr/local/bin/tsos-firstboot
TimeoutStartSec=infinity
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  log "Cloning tabby-stack for first boot"
  if ! arch-chroot "$TARGET" /usr/bin/runuser -u "$TARGET_USER" -- \
    git clone "$TABBY_REPO" "$stack_home"; then
    die "git clone failed. Check network, then re-run. Repo: $TABBY_REPO"
  fi
  arch-chroot "$TARGET" /usr/bin/systemctl enable tsos-tabby-firstboot.service
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

  local runner="$TARGET/home/${TARGET_USER}/run-omarchy.sh"
  cat >"$runner" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export HOME="/home/${TARGET_USER}"
export USER="${TARGET_USER}"
export LOGNAME="${TARGET_USER}"
export OMARCHY_CHROOT_INSTALL=1
export OMARCHY_ONLINE_INSTALL=true
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
  rm -f "$runner"

  if ((status != 0)); then
    warn "Omarchy installer exited with status $status."
    warn "The Arch base is installed and should boot."
    warn "After you unlock the disk (if encrypted) and log in as ${TARGET_USER}, run: install-omarchy"
    return 0
  fi
  log "Omarchy installer finished"
}

cleanup() {
  log "Cleaning installer files from the target"
  rm -f "$TARGET/root/configure-arch.sh"
  if [[ -f "$TARGET/root/install-vars.sh" ]]; then
    sed -i '/_PASSWORD=/d' "$TARGET/root/install-vars.sh" || true
  fi
  log "Unmounting"
  umount -R "$TARGET" || true
  if ((ENCRYPT)) && [[ -e "/dev/mapper/$CRYPT_NAME" ]]; then
    cryptsetup close "$CRYPT_NAME" || true
  fi
}

final_message() {
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
  The repo is already at /home/${TARGET_USER}/tabby-stack
  A first-boot service (tsos-tabby-firstboot) runs install.sh after reboot.
  Linger is on, so that happens without a graphical login.
  Model set: ${TABBY_MODELS}
  API:       http://${TABBY_NETWORK_HOST}:${TABBY_NETWORK_PORT}
  UI:        http://127.0.0.1:${TABBY_NETWORK_PORT}/v1/ui
  Watch:     journalctl -u tsos-tabby-firstboot -f
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
    later)
      cat <<EOF
Omarchy was not installed yet. After login run:

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

main() {
  parse_args "$@"
  attach_console
  early_preflight
  if ((CONFIG_PROVIDED)); then
    pick_disk_if_needed
  else
    prompt_settings
  fi
  validate_names
  require_disk
  assign_partition_numbers
  print_plan
  if ((DRY_RUN)); then
    log "dry-run: no changes made"
    exit 0
  fi
  preflight
  confirm_wipe
  collect_passwords
  log "Starting the install..."
  disable_live_mkinitcpio_hooks
  timedatectl set-ntp true || true
  wipe_and_partition
  setup_storage
  install_base
  write_chroot_files
  configure_chroot
  write_tabby_bootstrap
  install_omarchy_chroot
  cleanup
  final_message
}

main "$@"
